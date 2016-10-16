""" YOLO detection demo in Caffe """
from __future__ import print_function, division

import getopt
import sys
from datetime import datetime

import numpy as np

import cv2

import caffe


USE_GPU = False

if USE_GPU:
    GPU_ID = 0 # Switch between 0 and 1 depending on the GPU you want to use.
    caffe.set_mode_gpu()
    caffe.set_device(GPU_ID)
else:
    caffe.set_mode_cpu()


def get_boxes(output, img_size, grid_size, num_boxes):
    """ extract bounding boxes from the last layer """

    w_img, h_img = img_size[1], img_size[0]
    boxes = np.reshape(output, (grid_size, grid_size, num_boxes, 4))

    offset = np.tile(np.arange(grid_size)[:, np.newaxis], (grid_size, 1, num_boxes))

    boxes[:, :, :, 0] += offset
    boxes[:, :, :, 1] += np.transpose(offset, (1, 0, 2))
    boxes[:, :, :, 0:2] /= 7.0
    # the predicted size is the square root of the box size
    boxes[:, :, :, 2:4] *= boxes[:, :, :, 2:4]

    boxes[:, :, :, [0, 2]] *= w_img
    boxes[:, :, :, [1, 3]] *= h_img

    return boxes


def parse_yolo_output(output, img_size):
    """ convert the output of YOLO's last layer to boxes and confidence in each
    class """

    num_classes = 20
    num_boxes = 2
    grid_size = 7

    sc_offset = grid_size * grid_size * num_classes
    box_offset = sc_offset + grid_size * grid_size * num_boxes

    class_probs = np.reshape(output[0:sc_offset], (grid_size, grid_size, num_classes))
    confidences = np.reshape(output[sc_offset:box_offset], (grid_size, grid_size, num_boxes))

    probs = np.zeros((grid_size, grid_size, num_boxes, num_classes))
    for i in range(num_boxes):
        for j in range(num_classes):
            probs[:, :, i, j] = class_probs[:, :, j] * confidences[:, :, i]

    boxes = get_boxes(output[box_offset:], img_size, grid_size, num_boxes)

    return boxes, probs


def get_candidate_objects(output, img_size):
    """ convert network output to bounding box predictions """

    classes = ["aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car",
               "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
               "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor"]

    threshold = 0.2
    iou_threshold = 0.5

    boxes, probs = parse_yolo_output(output, img_size)

    filter_mat_probs = (probs >= threshold)
    filter_mat_boxes = np.nonzero(filter_mat_probs)[0:3]
    boxes_filtered = boxes[filter_mat_boxes]
    probs_filtered = probs[filter_mat_probs]
    classes_num_filtered = np.argmax(filter_mat_probs, axis=3)[filter_mat_boxes]

    idx = np.argsort(probs_filtered)[::-1]
    boxes_filtered = boxes_filtered[idx]
    probs_filtered = probs_filtered[idx]
    classes_num_filtered = classes_num_filtered[idx]

    # Non-Maxima Suppression: greedily suppress low-score overlapped boxes
    for i, box_filtered in enumerate(boxes_filtered):
        if probs_filtered[i] == 0:
            continue
        for j in range(i+1, len(boxes_filtered)):
            if iou(box_filtered, boxes_filtered[j]) > iou_threshold:
                probs_filtered[j] = 0.0

    filter_iou = (probs_filtered > 0.0)
    boxes_filtered = boxes_filtered[filter_iou]
    probs_filtered = probs_filtered[filter_iou]
    classes_num_filtered = classes_num_filtered[filter_iou]

    result = []
    for class_id, box, prob in zip(classes_num_filtered, boxes_filtered, probs_filtered):
        result.append([classes[class_id], box[0], box[1], box[2], box[3], prob])

    return result


def iou(box1, box2):
    """ compute intersection over union score """
    int_tb = min(box1[0]+0.5*box1[2], box2[0]+0.5*box2[2]) - \
             max(box1[0]-0.5*box1[2], box2[0]-0.5*box2[2])
    int_lr = min(box1[1]+0.5*box1[3], box2[1]+0.5*box2[3]) - \
             max(box1[1]-0.5*box1[3], box2[1]-0.5*box2[3])
    intersection = max(0.0, int_tb) * max(0.0, int_lr)

    return intersection / (box1[2]*box1[3] + box2[2]*box2[3] - intersection)


def draw_box(img, name, box, score):
    """ draw a single bounding box on the image """
    xmin, ymin, xmax, ymax = box

    box_tag = '{} : {:.2f}'.format(name, score)
    text_x, text_y = 5, 7

    cv2.rectangle(img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
    boxsize, _ = cv2.getTextSize(box_tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(img, (xmin, ymin-boxsize[1]-text_y),
                  (xmin+boxsize[0]+text_x, ymin), (0, 225, 0), -1)
    cv2.putText(img, box_tag, (xmin+text_x, ymin-text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)


def show_results(img, results):
    """ draw bounding boxes on the image """
    img_width, img_height = img.shape[1], img.shape[0]
    disp_console = True
    imshow = True

    for result in results:
        box_x, box_y, box_w, box_h = [int(v) for v in result[1:5]]
        if disp_console:
            print('    class : {}, [x,y,w,h]=[{:d},{:d},{:d},{:d}], Confidence = {}'.\
                format(result[0], box_x, box_y, box_w, box_h, str(result[5])))
        xmin, xmax = max(box_x-box_w//2, 0), min(box_x+box_w//2, img_width)
        ymin, ymax = max(box_y-box_h//2, 0), min(box_y+box_h//2, img_height)

        if imshow:
            draw_box(result[0], (xmin, ymin, xmax, ymax), result[5])
    if imshow:
        cv2.imshow('YOLO detection', img)


def detect(model_filename, weight_filename, img_filename):
    """ given a YOLO caffe model and an image, detect the objects in the image
    """
    net = caffe.Net(model_filename, weight_filename, caffe.TEST)
    img = caffe.io.load_image(img_filename) # load the image using caffe.io

    transformer = caffe.io.Transformer({'data': net.blobs['data'].data.shape})
    transformer.set_transpose('data', (2, 0, 1))
    transformer.set_channel_swap('data', (2, 1, 0))

    t_start = datetime.now()
    out = net.forward_all(data=np.asarray([transformer.preprocess('data', img)]))
    t_end = datetime.now()
    print('total time is {:.2f} milliseconds'.format((t_end-t_start).total_seconds()*1e3))

    img_cv = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    results = get_candidate_objects(out['result'][0], img.shape)
    show_results(img_cv, results)
    cv2.waitKey()


def main(argv):
    """ script entry point """
    model_filename = ''
    weight_filename = ''
    img_filename = ''
    usage_message = 'Usage: yolo_detect.py -m <model_file> -w <output_file> -i <img_file>'

    try:
        opts, _ = getopt.getopt(argv, "hm:w:i:")
        print(opts)
    except getopt.GetoptError:
        print(usage_message)
        return
    if not opts:
        print(usage_message)
        return

    for opt, arg in opts:
        if opt == '-h':
            print(usage_message)
            return
        elif opt == "-m":
            model_filename = arg
        elif opt == "-w":
            weight_filename = arg
        elif opt == "-i":
            img_filename = arg
    print('model file is {}'.format(model_filename))
    print('weight file is {}'.format(weight_filename))
    print('image file is {}'.format(img_filename))

    detect(model_filename, weight_filename, img_filename)


if __name__ == '__main__':
    main(sys.argv[1:])