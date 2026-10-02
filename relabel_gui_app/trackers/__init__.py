"""Link per-frame boxes into tracks. Every method takes the same input and returns the same output;
pick one by id with run(frames, method=...). describe() lists them for the UI.

A tracker is any class with reset() and step(boxes, scores, classes) -> [int id per box]; it is
re-created per run and reset at every new video in a merged dataset.
"""
from .bytetrack import ByteTracker
from .common import np, sequence_key

METHODS = {
    "bytetrack": {
        "label": "ByteTrack (fast)",
        "description": "Predicts each object's motion and matches boxes by overlap, using weak "
                       "detections to keep tracks alive. Fast; best when objects move smoothly.",
        "make": ByteTracker,
    },
}
DEFAULT_METHOD = "bytetrack"


def describe():
    return [{"id": k, "label": m["label"], "description": m["description"]} for k, m in METHODS.items()]


def run(frames, method=DEFAULT_METHOD, id_prefix="trk#", **params):
    """frames: [{"file": str, "regions": [{"box": [x,y,w,h], "score": float|None, "cls": str}]}] in
    playback order. Returns {"ids": [[track id per region] per frame], "classes": {id: majority
    class}, "tracks": n, "sequences": n}."""
    if np is None:
        raise RuntimeError("tracking needs numpy: pip install numpy")
    if method not in METHODS:
        raise ValueError(f"unknown tracking method: {method}")
    tr = METHODS[method]["make"](**params)
    raw, seq, n_seq = [], object(), 0
    for fr in frames:
        key = sequence_key(fr["file"])
        if key != seq:                                   # new video in a merged dataset: start fresh
            seq, n_seq = key, n_seq + 1
            tr.reset()
        regs = fr["regions"]
        raw.append(tr.step([r["box"] for r in regs],
                           [1.0 if r.get("score") is None else float(r["score"]) for r in regs],
                           [r.get("cls") or "NONE" for r in regs]))
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
    return {"ids": ids, "classes": classes, "tracks": len(votes), "sequences": n_seq}
