"""Synthetic scenes with known identities, for tracker tests and tools/benchmark_trackers.py.

Each scene is a list of objects with a position function; frames hold boxes in random order with
optional jitter, missed boxes, weak scores and hidden spans (occlusion), plus the true id of every box.
"""
import math
import random


def _obj(oid, cls, size, path, hidden=()):
    return {"id": oid, "cls": cls, "size": size, "path": path, "hidden": hidden}


SCENES = {
    "smooth": [
        _obj("a", "car", (70, 70), lambda f: (20 + 12 * f, 60 + f)),
        _obj("b", "person", (40, 40), lambda f: (560 - 9 * f, 220 - f)),
        _obj("c", "car", (90, 90), lambda f: (200 + 5 * f, 250 - 2 * f)),
        _obj("d", "bicycle", (50, 50), lambda f: (320 - 4 * f, 30 + 3 * f)),
    ],
    # two cars disappear behind something for 45 frames, longer than the 30-frame track buffer
    "long occlusion": [
        _obj("a", "car", (80, 60), lambda f: (10 + 6 * f, 100), hidden=(30, 75)),
        _obj("b", "car", (80, 60), lambda f: (900 - 6 * f, 260), hidden=(35, 80)),
        _obj("c", "person", (30, 70), lambda f: (400 + 2 * math.sin(f / 5), 20 + 3 * f)),
    ],
    # two people walk through each other: overlapping boxes, the classic id-swap trap
    "crossing": [
        _obj("a", "person", (40, 90), lambda f: (100 + 8 * f, 200)),
        _obj("b", "person", (40, 90), lambda f: (900 - 8 * f, 210)),
        _obj("c", "person", (40, 90), lambda f: (500, 40 + 6 * f)),
    ],
    # sharp turns: the constant-velocity guess is wrong right after each turn
    "turns": [
        _obj("a", "car", (60, 60), lambda f: (100 + 10 * min(f, 30), 100 + 10 * max(0, f - 30))),
        _obj("b", "bicycle", (40, 40), lambda f: (600 + 70 * math.sin(f / 6), 300 + 4 * f)),
        _obj("c", "person", (30, 60), lambda f: (300 + 3 * f, 500 - 9 * abs((f % 20) - 10))),
    ],
}


def make(scene, n=90, seed=0, drop=0.0, jitter=2.0, weak_scores=False, prefix="clip"):
    rnd = random.Random(seed)
    frames, truth = [], []
    for f in range(n):
        regs, ids = [], []
        for o in SCENES[scene]:
            lo, hi = o["hidden"] or (n + 1, n + 1)
            if lo <= f < hi or rnd.random() < drop:
                continue
            x, y = o["path"](f)
            w, h = o["size"]
            box = [x + rnd.uniform(-jitter, jitter), y + rnd.uniform(-jitter, jitter), w, h]
            regs.append({"box": box, "score": rnd.uniform(0.2, 1.0) if weak_scores else None, "cls": o["cls"]})
            ids.append(o["id"])
        order = list(range(len(regs)))
        rnd.shuffle(order)
        frames.append({"file": f"{prefix}_frame_{f:06d}.jpg", "regions": [regs[i] for i in order]})
        truth.append([ids[i] for i in order])
    return frames, truth


def score(result, truth):
    """ids_per_object: mean number of track ids each true object was split into (1.0 is perfect).
    wrong_merges: track ids that cover more than one true object (0 is perfect)."""
    by_obj, by_tid = {}, {}
    for row_ids, row_truth in zip(result["ids"], truth):
        for tid, oid in zip(row_ids, row_truth):
            by_obj.setdefault(oid, set()).add(tid)
            by_tid.setdefault(tid, set()).add(oid)
    return {"ids_per_object": sum(len(v) for v in by_obj.values()) / max(1, len(by_obj)),
            "wrong_merges": sum(1 for v in by_tid.values() if len(v) > 1)}
