"""tracker.py — ByteTrack-style multi-object tracking over boxes that already exist in a project.

Given per-frame boxes (from any detector, or drawn by hand), link them into tracks so each physical
object gets one track id across frames. Follows ByteTrack (Zhang et al., ECCV 2022):
  * a constant-velocity Kalman filter predicts every track's box in the next frame;
  * HIGH-score boxes are matched to all live and recently lost tracks by IoU;
  * LOW-score boxes are then matched to the tracks still unmatched (stricter IoU), which keeps a
    track alive through occlusion instead of dropping the weak detection;
  * leftover boxes start new tracks; tracks unseen for `track_buffer` frames end.
Each track's class is the majority class of its boxes. ByteTracker documents where this differs
from the detector-facing original.

Needs numpy. Uses scipy's optimal assignment when installed, otherwise a greedy matcher.
"""
import re

try:
    import numpy as np
except ImportError:                                   # reported to the user by the /track route
    np = None

try:
    from scipy.optimize import linear_sum_assignment
except ImportError:
    linear_sum_assignment = None


# ---------------------------------------------------------------- Kalman filter
class KalmanBox:
    """Constant-velocity Kalman filter on (cx, cy, aspect, height) + their velocities.
    Noise scales with box height so large and small objects behave alike."""
    POS_STD, VEL_STD = 1.0 / 20, 1.0 / 160

    def __init__(self, xywh):
        z = self._to_z(xywh)
        self.x = np.r_[z, np.zeros(4)]
        h = z[3]
        std = np.array([2 * self.POS_STD * h, 2 * self.POS_STD * h, 1e-2, 2 * self.POS_STD * h,
                        10 * self.VEL_STD * h, 10 * self.VEL_STD * h, 1e-5, 10 * self.VEL_STD * h])
        self.P = np.diag(std ** 2)

    F = None
    H = None

    @classmethod
    def _mats(cls):
        if cls.F is None:
            cls.F = np.eye(8)
            cls.F[:4, 4:] = np.eye(4)
            cls.H = np.eye(4, 8)
        return cls.F, cls.H

    @staticmethod
    def _to_z(b):
        x, y, w, h = (float(v) for v in b)
        h = max(h, 1.0)
        return np.array([x + w / 2, y + h / 2, w / h, h])

    def predict(self):
        F, _ = self._mats()
        h = self.x[3]
        q = np.array([self.POS_STD * h, self.POS_STD * h, 1e-2, self.POS_STD * h,
                      self.VEL_STD * h, self.VEL_STD * h, 1e-5, self.VEL_STD * h])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + np.diag(q ** 2)

    def update(self, xywh):
        _, H = self._mats()
        h = self.x[3]
        r = np.array([self.POS_STD * h, self.POS_STD * h, 1e-1, self.POS_STD * h])
        S = H @ self.P @ H.T + np.diag(r ** 2)
        K = np.linalg.solve(S, H @ self.P).T          # P H^T S^-1 (S symmetric)
        self.x = self.x + K @ (self._to_z(xywh) - H @ self.x)
        self.P = (np.eye(8) - K @ H) @ self.P

    def box(self):
        cx, cy, a, h = self.x[:4]
        w = a * h
        return np.array([cx - w / 2, cy - h / 2, w, h])


# ---------------------------------------------------------------- association
def iou_matrix(a, b):
    """IoU between every box in a (N,4 xywh) and b (M,4 xywh)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ax2, ay2 = a[:, 0] + a[:, 2], a[:, 1] + a[:, 3]
    bx2, by2 = b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    iw = np.clip(np.minimum(ax2[:, None], bx2[None]) - np.maximum(a[:, 0, None], b[None, :, 0]), 0, None)
    ih = np.clip(np.minimum(ay2[:, None], by2[None]) - np.maximum(a[:, 1, None], b[None, :, 1]), 0, None)
    inter = iw * ih
    union = (a[:, 2] * a[:, 3])[:, None] + (b[:, 2] * b[:, 3])[None] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def assign(cost, max_cost):
    """Match rows to columns minimising cost, rejecting pairs above max_cost.
    Returns (matches [(r,c)], unmatched_rows, unmatched_cols)."""
    R, C = cost.shape
    if R == 0 or C == 0:
        return [], list(range(R)), list(range(C))
    if linear_sum_assignment is not None:
        big = max_cost + 1.0
        rows, cols = linear_sum_assignment(np.where(cost > max_cost, big, cost))
        pairs = [(r, c) for r, c in zip(rows, cols) if cost[r, c] <= max_cost]
    else:
        pairs, used_r, used_c = [], set(), set()
        for flat in np.argsort(cost, axis=None):
            r, c = divmod(int(flat), C)
            if cost[r, c] > max_cost:
                break
            if r not in used_r and c not in used_c:
                pairs.append((r, c))
                used_r.add(r)
                used_c.add(c)
    mr = {r for r, _ in pairs}
    mc = {c for _, c in pairs}
    return pairs, [r for r in range(R) if r not in mr], [c for c in range(C) if c not in mc]


# ---------------------------------------------------------------- tracker
class _Track:
    __slots__ = ("id", "kf", "last_frame", "votes")

    def __init__(self, tid, box, frame):
        self.id = tid
        self.kf = KalmanBox(box)
        self.last_frame = frame
        self.votes = {}


class ByteTracker:
    """ByteTrack association over existing annotations.

    Deliberate differences from the detector-facing original, because here every box is an annotation
    to keep rather than a detection that may be a false positive:
      * tracks start immediately instead of waiting for a second confident detection;
      * weak boxes may also re-attach to recently lost tracks (still behind the stricter IoU gate);
      * every box receives an id, and any leftover box above new_track_thresh starts a track.
    Without these, objects whose boxes are intermittently missing or weak fragment into many ids."""

    def __init__(self, high_thresh=0.5, low_thresh=0.1, new_track_thresh=0.1, match_iou=0.2,
                 track_buffer=30, class_aware=False):
        self.high, self.low, self.new_thresh = high_thresh, low_thresh, new_track_thresh
        self.max_cost = 1.0 - match_iou                 # cost = 1 - IoU
        self.buffer, self.class_aware = track_buffer, class_aware
        self.next_id = 1
        self.reset()

    def reset(self):
        self.tracked, self.lost = [], []
        self.frame = -1

    def _new(self, box, cls, frame):
        t = _Track(self.next_id, box, frame)
        t.votes[cls] = 1
        self.next_id += 1
        return t

    def _cost(self, tracks, dets, boxes, classes):
        c = 1.0 - iou_matrix([t.kf.box() for t in tracks], [boxes[d] for d in dets])
        if self.class_aware and len(tracks) and len(dets):
            for i, t in enumerate(tracks):
                tc = max(t.votes, key=t.votes.get) if t.votes else None
                for j, d in enumerate(dets):
                    if tc is not None and classes[d] != tc:
                        c[i, j] = 1.0 + self.max_cost   # never match across classes
        return c

    def step(self, boxes, scores, classes):
        """Track one frame. Returns a track id (int) for every box."""
        self.frame += 1
        f = self.frame
        out = [None] * len(boxes)
        high = [i for i, s in enumerate(scores) if s >= self.high]
        low = [i for i, s in enumerate(scores) if s < self.high]

        pool = self.tracked + self.lost
        for t in pool:
            t.kf.predict()

        def hit(t, d):
            t.kf.update(boxes[d])
            t.last_frame = f
            t.votes[classes[d]] = t.votes.get(classes[d], 0) + 1
            out[d] = t.id

        # 1) confident boxes vs every live or recently lost track
        m, ut, ud = assign(self._cost(pool, high, boxes, classes), self.max_cost)
        for r, c in m:
            hit(pool[r], high[c])
        rest = [pool[r] for r in ut]

        # 2) weak boxes (above low_thresh) vs tracks still unmatched, with a stricter IoU gate
        weak = [d for d in low if scores[d] >= self.low]
        m2, _, _ = assign(self._cost(rest, weak, boxes, classes), 0.5)
        for r, c in m2:
            hit(rest[r], weak[c])
        matched = {id(pool[r]) for r, _ in m} | {id(rest[r]) for r, _ in m2}

        # 3) leftovers: confident ones start tracks; any other box still gets its own single-frame id
        born = []
        for d in [high[c] for c in ud] + [d for d in low if out[d] is None]:
            t = self._new(boxes[d], classes[d], f)
            out[d] = t.id
            if scores[d] >= self.new_thresh:
                born.append(t)

        # 4) unmatched live tracks become lost; lost tracks expire after track_buffer frames
        self.tracked = [t for t in pool if id(t) in matched] + born
        self.lost = [t for t in pool if id(t) not in matched and f - t.last_frame <= self.buffer]
        return out


_TRAILING_NUM = re.compile(r"\d+(?=\D*$)")


def sequence_key(filename):
    """Frames of one video share this key: the filename with its last number (the frame index) removed."""
    return _TRAILING_NUM.sub("", filename)


def run(frames, id_prefix="trk#", **params):
    """frames: [{"file": str, "regions": [{"box": [x,y,w,h], "score": float|None, "cls": str}]}] in
    playback order. Returns {"ids": [[track id or "" per region] per frame], "classes": {id: class},
    "tracks": n, "sequences": n}."""
    if np is None:
        raise RuntimeError("tracking needs numpy: pip install numpy")
    tr = ByteTracker(**params)
    votes, ids, seq, n_seq = {}, [], object(), 0
    for fr in frames:
        key = sequence_key(fr["file"])
        if key != seq:                                   # new video in a merged dataset: start fresh
            seq, n_seq = key, n_seq + 1
            tr.reset()
        regs = fr["regions"]
        boxes = [r["box"] for r in regs]
        scores = [1.0 if r.get("score") is None else float(r["score"]) for r in regs]
        classes = [r.get("cls") or "NONE" for r in regs]
        out = tr.step(boxes, scores, classes)
        row = []
        for i, t in enumerate(out):
            tid = f"{id_prefix}{t}"
            v = votes.setdefault(tid, {})
            v[classes[i]] = v.get(classes[i], 0) + 1
            row.append(tid)
        ids.append(row)
    classes = {}
    for tid, v in votes.items():
        named = {c: n for c, n in v.items() if c != "NONE"} or v   # prefer a real class over NONE
        classes[tid] = max(named, key=named.get)
    return {"ids": ids, "classes": classes, "tracks": len(votes), "sequences": n_seq}
