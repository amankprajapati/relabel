#!/usr/bin/env python3
"""Generate a small synthetic tracked-box project to try the tool with (standard library only).

    python make_sample.py [OUT_DIR]      # default: ./sample_data

Writes OUT_DIR/frames/frame_000000.png ... and OUT_DIR/sample_via.json: a few coloured squares
moving across the frame, each with a stable track_id, plus a class list declared in the JSON.
"""
import json
import os
import struct
import sys
import zlib

W, H, N_FRAMES = 640, 360, 40
OBJECTS = [  # (track_id, class, start x, y, size, dx, dy, rgb)
    ("obj#1", "car", 20, 60, 70, 12, 1, (220, 70, 70)),
    ("obj#2", "person", 560, 220, 40, -9, -1, (70, 140, 230)),
    ("obj#3", "car", 200, 250, 90, 5, -2, (90, 200, 110)),
    ("obj#4", "bicycle", 320, 30, 50, -4, 3, (230, 190, 60)),
]
CLASSES = ["car", "person", "bicycle"]


def png(path, pixels):
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main(out):
    frames_dir = os.path.join(out, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    meta = {}
    for f in range(N_FRAMES):
        pixels = [[40, 44, 52] * W for _ in range(H)]
        regions = []
        for tid, cls, x0, y0, s, dx, dy, rgb in OBJECTS:
            x = max(0, min(W - s, x0 + dx * f))
            y = max(0, min(H - s, y0 + dy * f))
            for yy in range(y, y + s):
                row = pixels[yy]
                for xx in range(x, x + s):
                    row[3 * xx:3 * xx + 3] = rgb
            regions.append({"shape_attributes": {"name": "rect", "x": x, "y": y, "width": s, "height": s},
                            "region_attributes": {"class": cls, "track_id": tid}})
        name = f"frame_{f:06d}.png"
        png(os.path.join(frames_dir, name), pixels)
        size = os.path.getsize(os.path.join(frames_dir, name))
        meta[f"{name}{size}"] = {"filename": name, "size": size, "regions": regions,
                                 "file_attributes": {"frame": str(f)}}
    via = {"_via_img_metadata": meta,
           "_via_attributes": {"region": {"class": {"type": "dropdown", "description": "",
                                                    "options": {c: c for c in CLASSES},
                                                    "default_options": {}},
                                          "track_id": {"type": "text", "description": "",
                                                       "default_value": ""}},
                               "file": {}}}
    with open(os.path.join(out, "sample_via.json"), "w", encoding="utf-8") as fh:
        json.dump(via, fh, indent=1)
    print(f"wrote {N_FRAMES} frames + sample_via.json to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample_data")
