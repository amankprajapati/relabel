"""Building blocks shared by every tracker: a box Kalman filter, IoU, optimal matching, and
splitting a merged dataset into per-video sequences.

Needs numpy. Uses scipy's optimal assignment when installed, otherwise a greedy matcher.
"""
import re

try:
    import numpy as np
except ImportError:                                   # reported to the user by trackers.run
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


_TRAILING_NUM = re.compile(r"\d+(?=\D*$)")


def sequence_key(filename):
    """Frames of one video share this key: the filename with its last number (the frame index) removed."""
    return _TRAILING_NUM.sub("", filename)
