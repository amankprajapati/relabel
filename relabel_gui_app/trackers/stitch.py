"""stitch.py — offline second pass that rejoins tracks broken by long occlusions or missed boxes.

Online trackers must give up on an object after `track_buffer` frames; when it comes back it gets a
new id. With the whole video available we can look both ways: for every track that ends and every
track that starts later, extrapolate each one's motion across the gap and score how well the two
meet. Pairs that never coexist in time, whose extrapolated boxes overlap and whose sizes agree
are joined, best pairs first, one successor per track (so chains A -> B -> C also form).
"""
from .common import assign, iou_matrix, np


class _Piece:
    def __init__(self, tid):
        self.id, self.frames, self.boxes, self.classes = tid, [], [], {}

    def add(self, frame, box, cls):
        self.frames.append(frame)
        self.boxes.append(np.asarray(box, float))
        self.classes[cls] = self.classes.get(cls, 0) + 1

    def velocity(self, at_end, k=5):
        """Mean per-frame box change over the last (or first) k observations."""
        idx = range(max(0, len(self.frames) - k), len(self.frames)) if at_end else range(min(k, len(self.frames)))
        idx = list(idx)
        if len(idx) < 2:
            return np.zeros(4)
        a, b = idx[0], idx[-1]
        return (self.boxes[b] - self.boxes[a]) / max(1, self.frames[b] - self.frames[a])

    def main_class(self):
        return max(self.classes, key=self.classes.get)


def _moved(box, vel, frames):
    b = box + vel * frames
    b[2], b[3] = max(b[2], 2.0), max(b[3], 2.0)
    return b


def stitch(ids_per_frame, boxes_per_frame, classes_per_frame, max_gap=90, min_iou=0.1,
           class_aware=False, motion_horizon=15):
    """Return a mapping old id -> new id that merges broken tracks within one sequence. Each
    candidate join is scored under three guesses of what happened in the gap: the object kept its
    velocity, kept it for only motion_horizon frames, or stopped; the best guess counts."""
    def horizons(gap):
        return (gap, min(gap, motion_horizon), 0)

    pieces = {}
    for f, (ids, boxes, classes) in enumerate(zip(ids_per_frame, boxes_per_frame, classes_per_frame)):
        for tid, box, cls in zip(ids, boxes, classes):
            pieces.setdefault(tid, _Piece(tid)).add(f, box, cls)
    plist = list(pieces.values())
    if not plist:
        return {}
    ends = starts = plist                                # every piece can be either side of a join
    cost = np.full((len(ends), len(starts)), 9.0)
    for i, a in enumerate(ends):
        a_end, a_box, a_vel = a.frames[-1], a.boxes[-1], a.velocity(True)
        for j, b in enumerate(starts):
            gap = b.frames[0] - a_end
            if b is a or gap < 1 or gap > max_gap:
                continue
            if class_aware and a.main_class() != b.main_class():
                continue
            b_box, b_vel = b.boxes[0], b.velocity(False)
            size = (a_box[2] * a_box[3]) / max(1.0, b_box[2] * b_box[3])
            if not 0.4 <= size <= 2.5:
                continue
            # the object may have kept going (full gap), slowed down (capped) or waited (no motion)
            score = max(iou_matrix([_moved(a_box.copy(), a_vel, h)], [b_box])[0, 0] for h in horizons(gap))
            score = max(score, max(iou_matrix([_moved(b_box.copy(), -b_vel, h)], [a_box])[0, 0]
                                   for h in horizons(gap)))
            if score < min_iou:
                continue
            penalty = 0.0 if a.main_class() == b.main_class() else 0.15
            cost[i, j] = 1.0 - score + penalty + 0.002 * gap        # prefer shorter gaps on ties
    pairs, _, _ = assign(cost, 1.0 - min_iou + 0.15 + 0.002 * max_gap)
    successor = {ends[i].id: starts[j].id for i, j in pairs if cost[i, j] < 9.0}
    predecessor = {v: k for k, v in successor.items()}
    mapping = {}
    for p in plist:                                      # walk each chain back to its first piece
        root = p.id
        while root in predecessor:
            root = predecessor[root]
        if root != p.id:
            mapping[p.id] = root
    return mapping

