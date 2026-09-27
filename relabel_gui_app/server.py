"""server.py — the HTTP layer: request routing over the model + assets. Stdlib http.server only.

Routes
  GET  /          -> the app page (render_index)
  GET  /ls        -> directory listing for the Open dialog     (fsbrowse.listdir_info)
  GET  /clips     -> current project list + compare flag
  GET  /clipdata  -> frames/regions/options for one clip        (Clip.clipdata)
  GET  /frame     -> a single frame image
  POST /save      -> write edits to the .edited.json            (Clip.save_state)
  POST /validate  -> pre-compare A/B compatibility check        (compare.validate_pair)
  POST /open      -> open a project (single or compare) chosen in the GUI
  POST /track     -> link boxes into tracks with ByteTrack        (tracker.run)
"""
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from clip import Clip
from compare import COMPARE, clear_compare, load_compare, validate_pair
from fsbrowse import listdir_info
from render import render_index
import tracker


def make_handler(clips, default_classes=()):
    """Build a request handler bound to the mutable `clips` dict (name -> Clip).
    default_classes: classes from --classes, offered in addition to each project's own."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code, ctype, body):
            try:
                self.send_response(code); self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, obj, code=200):
            self._send(code, "application/json", json.dumps(obj).encode())

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            u = urlparse(self.path); q = parse_qs(u.query)
            if u.path == "/":
                self._send(200, "text/html; charset=utf-8", render_index(clips, list(default_classes)).encode())
            elif u.path == "/ls":                     # server-side directory browser
                self._json(listdir_info(q.get("path", [""])[0]))
            elif u.path == "/clips":                  # current project list + compare flag
                self._json({"clips": list(clips), "compare": COMPARE["on"]})
            elif u.path == "/clipdata":
                c = q.get("clip", [""])[0]
                self._json(clips[c].clipdata()) if c in clips else self._send(404, "text/plain", b"no clip")
            elif u.path == "/frame":
                c = q.get("clip", [""])[0]; fn = os.path.basename(q.get("f", [""])[0])
                if c in clips:
                    fp = os.path.join(clips[c].frames_dir, fn)
                    if os.path.isfile(fp):
                        ctype = mimetypes.guess_type(fp)[0] or "image/jpeg"
                        with open(fp, "rb") as fh:      # 'with' so the handle closes (matters on Windows)
                            self._send(200, ctype, fh.read())
                        return
                self._send(404, "text/plain", b"no frame")
            else:
                self._send(404, "text/plain", b"404")

        def do_POST(self):
            p = urlparse(self.path).path
            if p == "/save":
                body = self._body(); c = body.get("clip")
                total = clips[c].save_state(body.get("cls", {}), body.get("edits", {}), body.get("classes")) if c in clips else 0
                print(f"saved [{c}]: {total} regions")
                self._json({"ok": True, "regions": total})
            elif p == "/track":                       # ByteTrack over the boxes the client sends
                b = self._body()
                prm = b.get("params") or {}
                kw = {k: float(prm[k]) for k in ("high_thresh", "low_thresh", "match_iou") if k in prm}
                if "track_buffer" in prm:
                    kw["track_buffer"] = int(prm["track_buffer"])
                kw["class_aware"] = bool(prm.get("class_aware"))
                try:
                    res = tracker.run(b.get("frames") or [], id_prefix=str(b.get("id_prefix") or "trk#"), **kw)
                    print(f"tracked: {res['tracks']} tracks over {res['sequences']} sequence(s)")
                    self._json({"ok": True, **res})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)})
            elif p == "/validate":                    # check two jsons BEFORE comparing
                b = self._body()
                self._json(validate_pair(b.get("json_a", ""), b.get("json_b", ""), b.get("frames_dir", "")))
            elif p == "/open":                        # load a project (single or compare) from the GUI
                b = self._body()
                try:
                    jb = (b.get("json") or "").strip(); fr = (b.get("frames_dir") or "").strip()
                    ja = (b.get("compare_json") or "").strip()
                    if not jb or not os.path.isfile(jb):
                        raise ValueError(f"JSON not found: {jb or '(blank)'}")
                    clip = Clip.from_files(jb, fr)
                    if not os.path.isdir(clip.frames_dir):
                        raise ValueError(f"frames folder not found: {clip.frames_dir}")
                    rep = None
                    if ja:                            # compare mode: validate then load A
                        rep = validate_pair(ja, jb, clip.frames_dir)
                        if not rep["ok"]:
                            self._json({"ok": False, "report": rep}); return
                        load_compare(ja)
                    else:
                        clear_compare()
                    name = os.path.splitext(os.path.basename(jb))[0]
                    clips.clear(); clips[name] = clip
                    print(f"opened '{name}'  frames={clip.frames_dir}  compare={COMPARE['on']}")
                    self._json({"ok": True, "name": name, "compare": COMPARE["on"], "report": rep})
                except Exception as e:
                    self._json({"ok": False, "error": str(e)})
            else:
                self._send(404, "text/plain", b"404")
    return H
