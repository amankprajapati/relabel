"""fsbrowse.py — the server-side directory browser used by the in-GUI "Open" dialog.

Cross-platform: handles Windows drive letters and forward/back slashes; parent navigation is
computed here, not in the client, so it is correct on every OS.
"""
import os


def win_drives():
    """Existing drive roots on Windows (['C:\\\\', 'D:\\\\', ...]); [] elsewhere."""
    if os.name != "nt":
        return []
    import string
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def listdir_info(path):
    """Directory listing for the file browser. Returns dirs, *.json files, parent, and whether the
    folder already looks like a project (has frames/ or images/)."""
    if path == "::drives::":                        # virtual root above the drives (Windows)
        return {"path": "::drives::", "parent": "::drives::", "is_root": True, "absolute_entries": True,
                "dirs": win_drives(), "jsons": [], "has_frames": False, "has_images": False}
    path = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(path):
        path = os.path.dirname(path) or os.path.abspath(os.sep)
    dirs, jsons = [], []
    try:
        for n in sorted(os.listdir(path), key=str.lower):
            fp = os.path.join(path, n)
            try:
                if os.path.isdir(fp):
                    dirs.append(n)
                elif n.lower().endswith(".json"):
                    jsons.append(n)
            except OSError:                          # unreadable entry (permissions / dangling link)
                pass
    except (PermissionError, OSError):
        pass
    norm = os.path.normpath(path)
    parent = os.path.dirname(norm)
    is_root = parent == norm                         # at a filesystem root ("/" or "C:\")
    if is_root:
        parent = "::drives::" if os.name == "nt" else norm
    return {"path": path, "parent": parent, "is_root": is_root, "absolute_entries": False,
            "dirs": dirs, "jsons": jsons,
            "has_frames": os.path.isdir(os.path.join(path, "frames")),
            "has_images": os.path.isdir(os.path.join(path, "images"))}
