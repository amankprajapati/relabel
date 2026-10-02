"""Link per-frame boxes into tracks. Every method takes the same input and returns the same output;
pick one by id with run(frames, method=...). describe() lists them for the UI.

A tracker is any class with reset() and step(boxes, scores, classes) -> [int id per box]; it is
re-created per run and reset at every new video in a merged dataset. Methods marked "rejoin" also
run the offline stitch pass over each video afterwards.
"""
from .bytetrack import ByteTracker
from .common import np, sequence_key
from .ocsort import OCSortTracker
from .stitch import stitch

METHODS = {
    "bytetrack": {
        "label": "ByteTrack (fast)",
        "description": "Predicts each object's motion and matches boxes by overlap, using weak "
                       "detections to keep tracks alive. Fast; best when objects move smoothly.",
        "make": ByteTracker,
    },
    "ocsort": {
        "label": "OC-SORT (occlusion-robust)",
        "description": "Trusts real observations over predictions: recovers objects after "
                       "occlusions and sharp turns, and uses movement direction to keep crossing "
                       "objects apart. A little slower.",
        "make": OCSortTracker,
    },
    "ocsort-rejoin": {
        "label": "OC-SORT + rejoin (precise)",
        "description": "OC-SORT, then a second pass over the whole video rejoins tracks broken by "
                       "long occlusions or missed boxes. Slowest; fewest broken ids to merge by hand.",
        "make": OCSortTracker,
        "rejoin": True,
    },
}
DEFAULT_METHOD = "bytetrack"


def describe():
    return [{"id": k, "label": m["label"], "description": m["description"], "rejoin": bool(m.get("rejoin"))}
            for k, m in METHODS.items()]


def run(frames, method=DEFAULT_METHOD, id_prefix="trk#", rejoin_gap=90, **params):
    """frames: [{"file": str, "regions": [{"box": [x,y,w,h], "score": float|None, "cls": str}]}] in
    playback order. rejoin_gap: the longest break, in frames, the rejoin pass will bridge.
    Returns {"ids": [[track id per region] per frame], "classes": {id: majority class},
    "tracks": n, "sequences": n}."""
    if np is None:
        raise RuntimeError("tracking needs numpy: pip install numpy")
    if method not in METHODS:
        raise ValueError(f"unknown tracking method: {method}")
    spec = METHODS[method]
    tr = spec["make"](**params)
    raw, seq, starts = [], object(), []
    for k, fr in enumerate(frames):
        key = sequence_key(fr["file"])
        if key != seq:                                   # new video in a merged dataset: start fresh
            seq = key
            starts.append(k)
            tr.reset()
        regs = fr["regions"]
        raw.append(tr.step([r["box"] for r in regs],
                           [1.0 if r.get("score") is None else float(r["score"]) for r in regs],
                           [r.get("cls") or "NONE" for r in regs]))
    if spec.get("rejoin"):
        for a, b in zip(starts, starts[1:] + [len(frames)]):     # one video at a time
            part = frames[a:b]
            mapping = stitch(raw[a:b], [[r["box"] for r in f["regions"]] for f in part],
                             [[r.get("cls") or "NONE" for r in f["regions"]] for f in part],
                             max_gap=rejoin_gap, class_aware=params.get("class_aware", False))
            for k in range(a, b):
                raw[k] = [mapping.get(t, t) for t in raw[k]]
    votes, ids = {}, []
    for fr, row in zip(frames, raw):
        out = []
        for r, t in zip(fr["regions"], row):
            tid = f"{id_prefix}{t}"
            v = votes.setdefault(tid, {})
            c = r.get("cls") or "NONE"
            v[c] = v.get(c, 0) + 1
            out.append(tid)
        ids.append(out)
    classes = {}
    for tid, v in votes.items():
        named = {c: n for c, n in v.items() if c != "NONE"} or v   # prefer a real class over NONE
        classes[tid] = max(named, key=named.get)
    return {"ids": ids, "classes": classes, "tracks": len(votes), "sequences": len(starts)}
