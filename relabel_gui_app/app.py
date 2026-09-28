#!/usr/bin/env python3
"""app.py — entry point for Relabel, a web tool for reviewing and correcting tracked box annotations.

Run it directly:
    python3 relabel_gui_app/app.py [FOLDER] [--port 8001] [--classes a,b,c] [--compare ORIG.json] [--no-browser]
or as a module:
    python3 -m relabel_gui_app

FOLDER is optional: a clip folder (<stem>_via.json + frames/) or a parent of several. Omit it and
use the in-GUI "Open" dialog. Standard library only, except the optional tracker (numpy). Works on Windows.

Package layout:
    app.py        entry point (this file)         server.py    HTTP routing
    clip.py       Clip model + discovery          render.py    HTML assembly from web/ assets
    compare.py    two-JSON compare state/validate  fsbrowse.py  Open-dialog directory browser
    classdefs.py  class list sources               utils.py     shared helpers
    tracker.py    ByteTrack-style tracker (numpy)
    web/          index.html · style.css · app.js  (all presentation)
"""
import argparse
import os
import sys

# allow running this file directly (python3 app.py) AND as a module — put the package dir on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import ThreadingHTTPServer
import threading
import webbrowser

from classdefs import parse_classes_arg
from clip import discover
from compare import load_compare
from server import make_handler


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port that is already in use,
    # so launching twice would silently run two servers on one port. Fail loudly instead.
    allow_reuse_address = os.name != "nt"


def build_arg_parser():
    ap = argparse.ArgumentParser(description="Relabel: review and correct tracked box annotations")
    ap.add_argument("path", nargs="?", default=None,
                    help="optional: a clip folder or parent of several. Omit and use 'Open' in the GUI.")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--compare", default=None,
                    help="optional: a second VIA json (the original / before) to diff against on startup;"
                         " you can also pick both JSONs via 'Compare' in the GUI")
    ap.add_argument("--classes", default=None,
                    help="optional: extra classes to offer, as 'car,person,bike' or a text file with one per"
                         " line. Classes from the JSON are always included; you can also edit them in the GUI.")
    ap.add_argument("--no-browser", action="store_true", help="do not auto-open the web browser")
    return ap


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.compare:
        print(f"compare mode: loaded {load_compare(args.compare)} frames from {args.compare}")
    clips = discover(os.path.abspath(args.path)) if args.path else {}
    if args.path and not clips:
        sys.exit(f"no clips (folders with *_via.json + frames/) found under {args.path}")
    print(f"loaded {len(clips)} clip(s)" + (": " + ", ".join(clips) if clips else " — use 'Open' in the GUI"))
    url = f"http://localhost:{args.port}"
    try:
        srv = Server((args.host, args.port), make_handler(clips, parse_classes_arg(args.classes)))
    except OSError:
        sys.exit(f"port {args.port} is already in use. Relabel may already be running: open {url}, "
                 f"or start another copy with --port {args.port + 1}")
    print(f"open {url}  (Ctrl-C to stop)")
    if not args.no_browser:                              # auto-open a browser (nice on Windows double-click)
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
