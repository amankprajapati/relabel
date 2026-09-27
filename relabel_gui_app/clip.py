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
    """*_via.json (preferred) or *.json in a folder, EXCLUDING any .edited.json working files."""
    vias = [f for f in glob.glob(os.path.join(folder, "*_via.json")) if not is_edited_json(f)]
    if not vias:
        vias = [f for f in glob.glob(os.path.join(folder, "*.json")) if not is_edited_json(f)]
    return vias


class Clip:
    def __init__(self, folder):
        self.folder = folder
        # per-clip uses frames/; a merged/shared dataset uses images/ — accept either
        self.frames_dir = os.path.join(folder, "frames")
        if not os.path.isdir(self.frames_dir) and os.path.isdir(os.path.join(folder, "images")):
            self.frames_dir = os.path.join(folder, "images")
        vias = list_source_vias(folder)
        self.src_path = os.path.abspath(vias[0])        # ORIGINAL — read-only, never written
        self.out_path = edited_path_for(self.src_path)  # ALL saves go here
        # load the edited working file if it exists (resume), else the pristine original
        load_from = self.out_path if os.path.isfile(self.out_path) else self.src_path
        self.via = json.load(open(load_from, encoding="utf-8"))
        self.meta = self.via["_via_img_metadata"]

    @classmethod
    def from_files(cls, json_path, frames_dir=None):
        """Open a project from an explicit JSON + frames folder (in-GUI 'Open'). If frames_dir is
        blank, look for frames/ or images/ next to the JSON."""
        c = cls.__new__(cls)
        given = os.path.abspath(json_path)
        c.src_path = os.path.abspath(source_json_for(given))   # ORIGINAL — read-only
        c.out_path = edited_path_for(c.src_path)                # ALL saves go here
        c.folder = os.path.dirname(c.src_path)
        if frames_dir:
            c.frames_dir = os.path.abspath(frames_dir)
        else:
            c.frames_dir = os.path.join(c.folder, "frames")
            if not os.path.isdir(c.frames_dir) and os.path.isdir(os.path.join(c.folder, "images")):
                c.frames_dir = os.path.join(c.folder, "images")
        # if the user opened the .edited.json directly, load that; else resume from it when present
        load_from = given if is_edited_json(given) else (
            c.out_path if os.path.isfile(c.out_path) else c.src_path)
        c.via = json.load(open(load_from, encoding="utf-8"))
        c.meta = c.via["_via_img_metadata"]
        return c

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
                regs.append({"tid": tid, "box": [sa["x"], sa["y"], sa["width"], sa["height"]]})
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

    def save_state(self, cls, edits):
        by_name = {v["filename"]: v for v in self.meta.values()}
        for fn, regs in edits.items():
            v = by_name.get(fn)
            if v is None:
                continue
            v["regions"] = [{
                "shape_attributes": {"name": "rect", "x": int(b["box"][0]), "y": int(b["box"][1]),
                                     "width": int(b["box"][2]), "height": int(b["box"][3])},
                "region_attributes": {"class": cls.get(b["tid"], "NONE"),
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
    """Build {name: Clip} from a clip folder OR a parent of many clip folders."""
    if glob.glob(os.path.join(root, "*_via.json")):
        return {os.path.basename(os.path.normpath(root)): Clip(root)}   # normpath: works with \ too
    clips = {}
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if os.path.isdir(d) and glob.glob(os.path.join(d, "*_via.json")) \
                and (os.path.isdir(os.path.join(d, "frames")) or os.path.isdir(os.path.join(d, "images"))):
            clips[os.path.basename(d)] = Clip(d)
    return clips
