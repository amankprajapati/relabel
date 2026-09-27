"""render.py — assemble the single HTML page from the separate web/ assets.

Keeps presentation (web/index.html, web/style.css, web/app.js) out of the Python. The page is built
by injecting the CSS and JS into the HTML skeleton, then filling the per-request placeholders
(the clip dropdown options and the fallback class list).
"""
import json
import os

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _asset(name):
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


def render_index(clip_names, classes):
    """Return the full HTML document for `/`.
    clip_names: iterable of clip names for the top clip <select>.
    classes:    fallback class list injected as the JS `CLASSES` (overridden per-project from JSON)."""
    html = _asset("index.html")
    html = html.replace("{{STYLE}}", _asset("style.css")).replace("{{SCRIPT}}", _asset("app.js"))
    opts = "".join(f"<option>{c}</option>" for c in clip_names)
    return html.replace("__CLIP_OPTIONS__", opts).replace("__CLASSES__", json.dumps(classes))
