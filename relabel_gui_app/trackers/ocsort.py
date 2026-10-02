"""ocsort.py — OC-SORT-style tracking (Cao et al., "Observation-Centric SORT", CVPR 2023).

Same motion model as ByteTrack, but it trusts real observations over the filter's guesses:
  * observation-centric re-update: when a lost track is matched again, the filter is rewound to the
    last real box and replayed over the gap with interpolated boxes, so the error the filter built
    up while coasting through an occlusion does not survive the occlusion;
  * observation-centric momentum: a match also scores how well the direction from the track's last
    box to the candidate agrees with the direction the object has really been moving, which keeps
    ids apart when objects cross;
  * observation-centric recovery: tracks still unmatched get a second chance against their last
    observed box rather than the drifted prediction.
As in ByteTracker, tracks start on their first box and every box gets an id, because here every
box is an annotation to keep rather than a detection that may be a false positive.
"""
import math

from .common import KalmanBox, assign, iou_matrix, np


def _center(box):
    return np.array([box[0] + box[2] / 2.0, box[1] + box[3] / 2.0])


class _Track:
    __slots__ = ("id", "kf", "frozen", "obs", "last_frame", "votes")

    def __init__(self, tid, box, frame):
        self.id = tid
        self.kf = KalmanBox(box)
        self.frozen = (self.kf.x.copy(), self.kf.P.copy())     # filter state at the last real box
        self.obs = {frame: list(box)}                           # frame -> observed box
        self.last_frame = frame
        self.votes = {}

    def last_box(self):
        return self.obs[self.last_frame]

    def direction(self, delta):
        """Unit vector of the observed motion over about `delta` frames (zero if unknown)."""
        frames = sorted(self.obs)
        if len(frames) < 2:
            return np.zeros(2)
        earlier = [f for f in frames if f <= self.last_frame - delta] or frames[:1]
        d = _center(self.last_box()) - _center(self.obs[earlier[-1]])
        n = np.linalg.norm(d)
        return d / n if n > 1e-6 else np.zeros(2)


class OCSortTracker:
    def __init__(self, high_thresh=0.5, low_thresh=0.1, new_track_thresh=0.1, match_iou=0.2,
                 track_buffer=30, class_aware=False, delta_t=3, inertia=0.2):
        self.low, self.new_thresh = low_thresh, new_track_thresh
        self.high = high_thresh                    # unused by OC-SORT's single pass; kept for a uniform API
        self.min_iou, self.buffer, self.class_aware = match_iou, track_buffer, class_aware
        self.delta_t, self.inertia = delta_t, inertia
        self.next_id = 1
        self.reset()

    def reset(self):
        self.tracks = []
        self.frame = -1

    def _gate_classes(self, iou, tracks, dets, classes):
        if self.class_aware:
            for i, t in enumerate(tracks):
                tc = max(t.votes, key=t.votes.get) if t.votes else None
                for j, d in enumerate(dets):
                    if tc is not None and classes[d] != tc:
                        iou[i, j] = 0.0
        return iou

    def _momentum(self, tracks, dets, boxes, scores):
        """Direction agreement in [-0.5, 0.5] per (track, det), weighted by detection score."""
        m = np.zeros((len(tracks), len(dets)))
        for i, t in enumerate(tracks):
            v = t.direction(self.delta_t)
            if not v.any():
                continue
            c0 = _center(t.last_box())
            for j, d in enumerate(dets):
                u = _center(boxes[d]) - c0
                n = np.linalg.norm(u)
                if n < 1e-6:
                    continue
                angle = math.acos(max(-1.0, min(1.0, float(np.dot(v, u / n)))))
                m[i, j] = (math.pi / 2 - angle) / math.pi * scores[d]
        return m

    def _match(self, iou, bonus):
        """Maximise IoU + bonus, never accepting a pair below the IoU gate."""
        cost = np.where(iou >= self.min_iou, 1.0 - iou - bonus, 3.0)
        return assign(cost, 2.0)

    def _hit(self, t, box, cls):
        f = self.frame
        if f - t.last_frame > 1:                    # re-found after a gap: replay it from the real box
            t.kf.x, t.kf.P = t.frozen[0].copy(), t.frozen[1].copy()
            a, b = np.array(t.last_box(), float), np.array(box, float)
            gap = f - t.last_frame
            for k in range(1, gap + 1):
                t.kf.predict()
                t.kf.update(a + (b - a) * k / gap)
        else:
            t.kf.update(box)
        t.frozen = (t.kf.x.copy(), t.kf.P.copy())
        t.obs[f] = list(box)
        t.last_frame = f
        t.votes[cls] = t.votes.get(cls, 0) + 1

    def step(self, boxes, scores, classes):
        self.frame += 1
        out = [None] * len(boxes)
        for t in self.tracks:
            t.kf.predict()
        dets = [i for i, s in enumerate(scores) if s >= self.low]
        tracks = self.tracks

        # 1) predicted boxes, IoU plus direction agreement
        iou = self._gate_classes(iou_matrix([t.kf.box() for t in tracks], [boxes[d] for d in dets]),
                                 tracks, dets, classes)
        m, ut, ud = self._match(iou, self.inertia * self._momentum(tracks, dets, boxes, scores))
        for r, c in m:
            self._hit(tracks[r], boxes[dets[c]], classes[dets[c]])
            out[dets[c]] = tracks[r].id
        rest_t, rest_d = [tracks[r] for r in ut], [dets[c] for c in ud]

        # 2) recovery: leftovers against each track's last observed box
        iou2 = self._gate_classes(iou_matrix([t.last_box() for t in rest_t], [boxes[d] for d in rest_d]),
                                  rest_t, rest_d, classes)
        m2, _, ud2 = self._match(iou2, 0.0)
        for r, c in m2:
            self._hit(rest_t[r], boxes[rest_d[c]], classes[rest_d[c]])
            out[rest_d[c]] = rest_t[r].id

        # 3) leftovers start tracks; boxes below low_thresh still get their own single-frame id
        for d in [rest_d[c] for c in ud2] + [i for i, s in enumerate(scores) if s < self.low]:
            t = _Track(self.next_id, boxes[d], self.frame)
            t.votes[classes[d]] = 1
            self.next_id += 1
            out[d] = t.id
            if scores[d] >= self.new_thresh:
                self.tracks.append(t)

        self.tracks = [t for t in self.tracks if self.frame - t.last_frame <= self.buffer]
        return out
