"""compare.py — "Compare two JSONs" support: the A-vs-B state, VIA parsing, and pre-compare validation.

The actual per-box difference logic (what changed / highlighting) lives in the client (web/app.js);
this module only loads the "before" (A) regions and validates that A and B describe the same frames.
"""
import json
import os

# Compare mode: original labels to diff the (corrected) working set against.
# by_file: filename -> [{tid, cls, box}] from the --compare json.
COMPARE = {"on": False, "by_file": {}}


def via_regions_by_file(path):
    """path -> {filename: [{tid,cls,box}]}. Raises ValueError if not a VIA json."""
    doc = json.load(open(path, encoding="utf-8"))
    meta = doc.get("_via_img_metadata")
    if not isinstance(meta, dict) or not meta:
        raise ValueError("not a VIA project (missing/empty _via_img_metadata)")
    out = {}
    for v in meta.values():
        out[v["filename"]] = [
            {"tid": r["region_attributes"].get("track_id", "?"),
             "cls": r["region_attributes"].get("class", "NONE"),
             "box": [r["shape_attributes"]["x"], r["shape_attributes"]["y"],
                     r["shape_attributes"]["width"], r["shape_attributes"]["height"]]}
            for r in v.get("regions", [])]
    return out


def load_compare(path):
    COMPARE["by_file"] = via_regions_by_file(path)   # reset + load (idempotent)
    COMPARE["on"] = True
    return len(COMPARE["by_file"])


def clear_compare():
    COMPARE["on"] = False
    COMPARE["by_file"] = {}


def validate_pair(json_a, json_b, frames_dir=None):
    """Robust, SET-BASED compatibility check between two VIA jsons before comparing.
    Matches frames by FILENAME (not the VIA filename+size key, so re-extracted frames still match).
    Returns {ok, errors[], warnings[], info{}}."""
    rep = {"ok": False, "errors": [], "warnings": [], "info": {}}
    A = B = None
    try:
        A = via_regions_by_file(json_a)
    except Exception as e:
        rep["errors"].append(f"A ({os.path.basename(json_a)}): {e}")
    try:
        B = via_regions_by_file(json_b)
    except Exception as e:
        rep["errors"].append(f"B ({os.path.basename(json_b)}): {e}")
    if rep["errors"]:
        return rep
    sa, sb = set(A), set(B)
    common, only_a, only_b = sa & sb, sa - sb, sb - sa
    same = os.path.abspath(json_a) == os.path.abspath(json_b)
    rep["info"] = {"a_frames": len(sa), "b_frames": len(sb), "common": len(common),
                   "only_a": len(only_a), "only_b": len(only_b), "same_file": same,
                   "only_a_ex": sorted(only_a)[:3], "only_b_ex": sorted(only_b)[:3]}
    if not common:
        rep["errors"].append("A and B share NO frame filenames — they look like different "
                             "datasets; cannot compare.")
        return rep
    if same:
        rep["warnings"].append("A and B are the same file → expect 0 differences.")
    if only_a or only_b:
        ratio = len(common) / max(len(sa), len(sb))
        msg = (f"frame sets differ: {len(common)} common, {len(only_a)} only in A, "
               f"{len(only_b)} only in B. Comparison will run on the {len(common)} common frames.")
        (rep["errors"] if ratio < 0.05 else rep["warnings"]).append(msg)
    if frames_dir and os.path.isdir(frames_dir):
        miss = sum(1 for f in common if not os.path.isfile(os.path.join(frames_dir, f)))
        rep["info"]["missing_on_disk"] = miss
        if miss:
            rep["warnings"].append(f"{miss}/{len(common)} common frames are not in the frames "
                                   f"folder (those images won't display).")
    rep["ok"] = not rep["errors"]
    return rep
