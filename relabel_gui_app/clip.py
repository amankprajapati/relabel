"""clip.py — the Clip model (load/serialize a VIA project) + project discovery + edited-file paths.

NON-DESTRUCTIVE EDITING: the original JSON is NEVER written. All saves (manual + autosave) go to a
sibling "<stem>.edited.json". Re-opening a project loads the edited file if it exists (so live edits
persist across sessions) while leaving the original untouched.
"""
import glob
import json
import os

from classdefs import class_options_of
from compare import COMPARE
from utils import natkey

EDITED_SUFFIX = ".edited.json"
SCORE_KEYS = ("score", "confidence", "conf")   # detector confidence, used by the tracker


def is_edited_json(path):
    return str(path).lower().endswith(EDITED_SUFFIX)


def edited_path_for(src):
    """foo_via.json -> foo_via.edited.json ; already-edited paths are returned unchanged."""
    src = str(src)
    if is_edited_json(src):
        return src
    base = src[:-5] if src.lower().endswith(".json") else src   # strip a trailing .json
    return base + EDITED_SUFFIX


def source_json_for(path):
    """The ORIGINAL file behind a possibly-edited path (foo_via.edited.json -> foo_via.json)."""
    path = str(path)
    if is_edited_json(path):
        return path[:-len(EDITED_SUFFIX)] + ".json"
    return path


def list_source_vias(folder):
    """The *_via.json files in a folder, excluding .edited.json working files."""
    return sorted(f for f in glob.glob(os.path.join(folder, "*_via.json")) if not is_edited_json(f))


def default_frames_dir(folder):
    """frames/ next to the JSON (per-clip layout), or images/ (merged-dataset layout)."""
    frames = os.path.join(folder, "frames")
    images = os.path.join(folder, "images")
    return images if not os.path.isdir(frames) and os.path.isdir(images) else frames


class Clip:
    def __init__(self, json_path, frames_dir=None):
        """A project: one VIA JSON plus its frames folder (default: frames/ or images/ beside it).
        json_path may be the original or its .edited.json; saves always go to the .edited.json."""
        given = os.path.abspath(json_path)
        self.src_path = os.path.abspath(source_json_for(given))   # ORIGINAL - read-only, never written
        self.out_path = edited_path_for(self.src_path)            # ALL saves go here
        self.folder = os.path.dirname(self.src_path)
        self.frames_dir = os.path.abspath(frames_dir) if frames_dir else default_frames_dir(self.folder)
        # opened the .edited.json directly: load it; otherwise resume from it when it exists
        load_from = given if is_edited_json(given) else (
            self.out_path if os.path.isfile(self.out_path) else self.src_path)
        with open(load_from, encoding="utf-8") as fh:
            self.via = json.load(fh)
        self.meta = self.via["_via_img_metadata"]

    def clipdata(self):
        tracks = {}
        frames = []
        untr = 0                     # counts untracked boxes (empty track_id) -> unique internal ids
        for v in self.meta.values():
            fr = int(v["file_attributes"].get("frame", -1))
            regs = []
            for r in v["regions"]:
                tid = r["region_attributes"].get("track_id", "")
                # Untracked box (e.g. wheels added externally have no track_id, by design). Give each
                # one a unique internal id ("@uN") so it is individually selectable/deletable; empty or
                # duplicate ids would otherwise collapse into one falsy identity the GUI can't act on.
                # save_state() writes track_id back as "" for these, so the on-disk data model is kept.
                if not tid or tid == "?":
                    tid = "@u%d" % untr
                    untr += 1
                sa = r["shape_attributes"]
                ra = r["region_attributes"]
                reg = {"tid": tid, "box": [sa["x"], sa["y"], sa["width"], sa["height"]]}
                extra = {k: v for k, v in ra.items() if k not in ("class", "track_id")}
                if extra:                   # kept on the box so saving never drops e.g. a score
                    reg["x"] = extra
                    score = next((extra[k] for k in SCORE_KEYS if k in extra), None)
                    try:
                        reg["s"] = float(score) if score not in (None, "") else None
                    except (TypeError, ValueError):
                        pass
                regs.append(reg)
                tracks.setdefault(tid, r["region_attributes"].get("class", "NONE"))
            frames.append({"f": fr, "file": v["filename"], "regions": regs,
                           "a": COMPARE["by_file"].get(v["filename"], [])})   # A (original) regions
        # order by FILENAME (video+window+frame), not the clip-local frame number, so a merged
        # dataset plays each clip's frames in sequence instead of interleaving clips
        frames.sort(key=lambda d: natkey(d["file"]))
        return {"tracks": dict(sorted(tracks.items())), "frames": frames, "compare": COMPARE["on"],
                "out_name": os.path.basename(self.out_path),       # where saves go (edited sibling)
                "src_name": os.path.basename(self.src_path),       # the untouched original
                "resumed": os.path.isfile(self.out_path),          # already had edits on disk
                "class_options": class_options_of(self.via)}       # dropdown options FROM this JSON

    def set_classes(self, labels):
        """Write the GUI's class list into _via_attributes.region.class.options, keeping the existing
        VIA key for labels that were already declared (new labels use the label as the key)."""
        region = self.via.setdefault("_via_attributes", {}).setdefault("region", {})
        attr = region.setdefault("class", {"type": "dropdown", "description": "", "default_options": {}})
        old = attr.get("options") or {}
        key_of = {(str(v) if v not in (None, "") else str(k)): k for k, v in old.items()}
        attr["options"] = {key_of.get(lbl, lbl): lbl for lbl in labels}

    def save_state(self, cls, edits, classes=None):
        if classes is not None:
            self.set_classes([str(c) for c in classes])
        by_name = {v["filename"]: v for v in self.meta.values()}
        for fn, regs in edits.items():
            v = by_name.get(fn)
            if v is None:
                continue
            v["regions"] = [{
                "shape_attributes": {"name": "rect", "x": int(b["box"][0]), "y": int(b["box"][1]),
                                     "width": int(b["box"][2]), "height": int(b["box"][3])},
                "region_attributes": {**(b.get("x") or {}), "class": cls.get(b["tid"], "NONE"),
                                      # untracked boxes ("@uN") are written back with an empty track_id
                                      "track_id": "" if str(b["tid"]).startswith("@u") else b["tid"]},
            } for b in regs]
        for v in self.meta.values():
            if v["filename"] in edits:
                continue
            for r in v["regions"]:
                t = r["region_attributes"].get("track_id")
                if t in cls:
                    r["region_attributes"]["class"] = cls[t]
        # NON-DESTRUCTIVE: write to the edited sibling, NEVER the original (self.src_path).
        # atomic write (temp + replace) with explicit UTF-8 — safe on Windows and Linux; a crash
        # mid-write can't leave a truncated file, and non-ASCII class/track ids survive.
        tmp = self.out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.via, fh)
        os.replace(tmp, self.out_path)
        return sum(len(v["regions"]) for v in self.meta.values())


def discover(root):
    """{name: Clip} for a project folder or a parent of several project folders. A folder may hold
    several *_via.json files sharing one frames folder; each becomes its own project."""
    folders = [root] if list_source_vias(root) else [
        d for d in sorted(glob.glob(os.path.join(root, "*")))
        if os.path.isdir(d) and list_source_vias(d) and os.path.isdir(default_frames_dir(d))]
    clips = {}
    for folder in folders:
        vias = list_source_vias(folder)
        base = os.path.basename(os.path.normpath(folder))           # normpath: works with \ too
        for via in vias:
            stem = os.path.basename(via)[:-len("_via.json")]
            clips[base if len(vias) == 1 else f"{base}/{stem}"] = Clip(via)
    return clips
