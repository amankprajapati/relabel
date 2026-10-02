# Street crossing example

60 frames (about 5 seconds at 12 fps, 960x540) of the Yonge and Dundas scramble crossing in
Toronto, with people, cars and trucks. Two projects share the `frames/` folder:

- `detections_via.json`: raw detector output. Every box has a class and a `score`, but no
  track id. Open it and press **Track** to link the boxes into objects.
- `tracked_via.json`: the same boxes already linked into tracks with Relabel's tracker. The
  labels are left exactly as the detector produced them, mistakes included: for example the
  grey pickup on the left is labelled `car`. Fix it once and every frame of it follows.

Boxes come from the YOLOX-S detector; `tools/build_example.py` rebuilds everything.

**Credits.** Video "Diagonal crosswalk at Yonge & Dundas in Toronto" by Raysonho @ Open Grid
Scheduler / Grid Engine, released under CC0 (public domain):
https://commons.wikimedia.org/wiki/File:DiagonalCrosswalkYongeDundas.webm.
Detector: YOLOX (Megvii, Apache-2.0) as packaged in the OpenCV model zoo.
