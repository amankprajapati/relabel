"""utils.py — small shared helpers with no external dependencies."""
import re


def natkey(s):
    """natural sort key: digit runs compared numerically (type-tagged to avoid int/str clashes).
    Sorting filenames <video>_clsNN_<start>s-<end>s_frame_NNNNNN.jpg by this keeps each clip's
    frames contiguous and in true numeric order (video -> class -> window -> frame)."""
    return [(0, int(t)) if t.isdigit() else (1, t) for t in re.findall(r"\d+|\D+", str(s))]
