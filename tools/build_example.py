#!/usr/bin/env python3
"""Rebuild the real-footage example project in examples/crossing (maintainers only).

    pip install opencv-python numpy scipy
    python tools/build_example.py

Steps: download a CC0 street video from Wikimedia Commons and the YOLOX-S detector from the
OpenCV model zoo, take a short clip of frames, detect road users in each frame, then write
two VIA projects that share one frames/ folder:

  detections_via.json   raw detector output: class + score per box, no track ids
  tracked_via.json      the same boxes linked into tracks with Relabel's ByteTrack

Video: "Diagonal crosswalk at Yonge & Dundas in Toronto" by Raysonho @ Open Grid Scheduler /
Grid Engine, CC0, https://commons.wikimedia.org/wiki/File:DiagonalCrosswalkYongeDundas.webm
Detector: YOLOX-S (Apache-2.0), https://huggingface.co/opencv/object_detection_yolox
"""
import json
import os
import shutil
import sys
import urllib.request

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relabel_gui_app"))
import tracker  # noqa: E402

VIDEO_URL = ("https://upload.wikimedia.org/wikipedia/commons/transcoded/d/d2/"
             "DiagonalCrosswalkYongeDundas.webm/DiagonalCrosswalkYongeDundas.webm.1080p.vp9.webm")
MODEL_URL = ("https://huggingface.co/opencv/object_detection_yolox/resolve/main/"
             "object_detection_yolox_2022nov.onnx")
OUT = os.path.join(ROOT, "examples", "crossing")
CACHE = os.path.join(ROOT, ".cache")

FIRST_FRAME, N_FRAMES, STEP = 300, 60, 2         # ~5 s of video at 12 fps
OUT_W, OUT_H = 960, 540
SCORE_MIN, NMS_IOU, MIN_BOX_H = 0.35, 0.45, 34   # MIN_BOX_H in output pixels: skips the far crowd
COCO_KEEP = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CLASSES = ["person", "bicycle", "car", "motorcycle", "bus", "truck"]


def fetch(url, name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.isfile(path):
        print(f"downloading {name} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "relabel-example-builder"})
        with urllib.request.urlopen(req) as r, open(path + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(path + ".part", path)
    return path


class YoloxDetector:
    """YOLOX-S through OpenCV DNN: letterbox to 640, decode the grid outputs, class-wise NMS."""
    SIZE = 640

    def __init__(self, model_path):
        self.net = cv2.dnn.readNet(model_path)
        grids, strides = [], []
        for s in (8, 16, 32):
            n = self.SIZE // s
            ys, xs = np.mgrid[0:n, 0:n]
            grids.append(np.stack((xs, ys), -1).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(strides).astype(np.float32)

    def __call__(self, img):
        h, w = img.shape[:2]
        r = min(self.SIZE / h, self.SIZE / w)
        canvas = np.full((self.SIZE, self.SIZE, 3), 114, np.uint8)
        canvas[:int(h * r), :int(w * r)] = cv2.resize(img, (int(w * r), int(h * r)))
        self.net.setInput(canvas.transpose(2, 0, 1)[None].astype(np.float32))
        out = self.net.forward()[0]
        xy = (out[:, :2] + self.grids) * self.strides
        wh = np.exp(out[:, 2:4]) * self.strides
        scores = out[:, 4:5] * out[:, 5:]
        cls = scores.argmax(1)
        conf = scores[np.arange(len(cls)), cls]
        keep = (conf >= SCORE_MIN) & np.isin(cls, list(COCO_KEEP))
        boxes = np.concatenate((xy - wh / 2, wh), 1)[keep] / r          # xywh in source pixels
        conf, cls = conf[keep], cls[keep]
        dets = []
        for c in np.unique(cls):
            m = np.where(cls == c)[0]
            for i in np.array(cv2.dnn.NMSBoxes(boxes[m].tolist(), conf[m].tolist(), SCORE_MIN, NMS_IOU)).flatten():
                dets.append((boxes[m[i]], float(conf[m[i]]), COCO_KEEP[int(c)]))
        return dets


def clip_box(b, sx, sy):
    x, y, w, h = b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(OUT_W, x + w), min(OUT_H, y + h)
    return [int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))]


def via_project(frames, regions_of):
    meta = {}
    for f in frames:
        meta[f["key"]] = {"filename": f["file"], "size": f["size"], "file_attributes": {"frame": str(f["index"])},
                          "regions": regions_of(f)}
    return {"_via_img_metadata": meta,
            "_via_attributes": {"region": {"class": {"type": "dropdown", "description": "",
                                                     "options": {c: c for c in CLASSES}, "default_options": {}},
                                           "track_id": {"type": "text", "description": "", "default_value": ""},
                                           "score": {"type": "text", "description": "detector confidence",
                                                     "default_value": ""}},
                                "file": {}}}


def region(box, cls, score, tid=""):
    return {"shape_attributes": {"name": "rect", "x": box[0], "y": box[1], "width": box[2], "height": box[3]},
            "region_attributes": {"class": cls, "track_id": tid, "score": round(score, 3)}}


def main():
    video = fetch(VIDEO_URL, "crossing.webm")
    detect = YoloxDetector(fetch(MODEL_URL, "yolox_s.onnx"))
    frames_dir = os.path.join(OUT, "frames")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(frames_dir)

    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, FIRST_FRAME)
    frames, src_index = [], FIRST_FRAME
    while len(frames) < N_FRAMES:
        ok, img = cap.read()
        if not ok:
            break
        if (src_index - FIRST_FRAME) % STEP == 0:
            sx, sy = OUT_W / img.shape[1], OUT_H / img.shape[0]
            dets = [(clip_box(b, sx, sy), s, c) for b, s, c in detect(img)]
            dets = [d for d in dets if d[0][3] >= MIN_BOX_H and d[0][2] >= 4]
            name = f"crossing_{src_index:06d}.jpg"
            path = os.path.join(frames_dir, name)
            cv2.imwrite(path, cv2.resize(img, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA),
                        [cv2.IMWRITE_JPEG_QUALITY, 72])
            size = os.path.getsize(path)
            frames.append({"file": name, "size": size, "key": f"{name}{size}", "index": src_index, "dets": dets})
        src_index += 1

    with open(os.path.join(OUT, "detections_via.json"), "w", encoding="utf-8") as fh:
        json.dump(via_project(frames, lambda f: [region(b, c, s) for b, s, c in f["dets"]]), fh)

    tracks = tracker.run([{"file": f["file"], "regions": [{"box": b, "score": s, "cls": c} for b, s, c in f["dets"]]}
                          for f in frames], id_prefix="obj#")
    ids = {f["file"]: row for f, row in zip(frames, tracks["ids"])}
    with open(os.path.join(OUT, "tracked_via.json"), "w", encoding="utf-8") as fh:
        json.dump(via_project(frames, lambda f: [region(b, tracks["classes"][t], s, t)
                                                 for (b, s, c), t in zip(f["dets"], ids[f["file"]])]), fh)

    n_boxes = sum(len(f["dets"]) for f in frames)
    print(f"{len(frames)} frames, {n_boxes} boxes, {tracks['tracks']} tracks -> {OUT}")


if __name__ == "__main__":
    main()
