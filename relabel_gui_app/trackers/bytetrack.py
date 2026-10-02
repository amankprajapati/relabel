"""bytetrack.py — ByteTrack-style multi-object tracking over boxes that already exist in a project.

Given per-frame boxes (from any detector, or drawn by hand), link them into tracks so each physical
object gets one track id across frames. Follows ByteTrack (Zhang et al., ECCV 2022):
  * a constant-velocity Kalman filter predicts every track's box in the next frame;
  * HIGH-score boxes are matched to all live and recently lost tracks by IoU;
  * LOW-score boxes are then matched to the tracks still unmatched (stricter IoU), which keeps a
    track alive through occlusion instead of dropping the weak detection;
  * leftover boxes start new tracks; tracks unseen for `track_buffer` frames end.
Each track's class is the majority class of its boxes. ByteTracker documents where this differs
from the detector-facing original.
"""
from .common import KalmanBox, assign, iou_matrix


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
