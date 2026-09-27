# relabel_gui_app — NDS review & correction GUI (modular)

A modular refactor of the single-file `relabel_gui.py`. Same behavior, split into small modules with
the presentation (HTML/CSS/JS) kept as separate web assets. **Standard library only** — no pip
packages, no Docker. Runs on Linux, macOS, and Windows.

## Run

```bash
python3 relabel_gui_app/app.py [FOLDER] [--port 8000] [--compare ORIG.json] [--no-browser]
# or, as a module:
python3 -m relabel_gui_app [FOLDER] ...
```

`FOLDER` (optional) is a clip folder (`<stem>_via.json` + `frames/`) or a parent of several. Omit it
and use the in-GUI **Open** dialog. It auto-opens your browser at `http://localhost:8000`.

## Layout

```
relabel_gui_app/
  app.py          entry point — arg parsing, project discovery, server startup, browser open
  __main__.py     enables `python3 -m relabel_gui_app`
  server.py       HTTP layer: routes requests over the model + assets (stdlib http.server)
  render.py       assembles the HTML page from web/ assets (injects CSS/JS, fills placeholders)
  clip.py         Clip model (load/serialize a VIA project), discovery, non-destructive .edited.json paths
  compare.py      "Compare two JSONs": before/after state, VIA parsing, pre-compare validation
  fsbrowse.py     server-side directory browser for the Open dialog (Windows drives, parent nav)
  classdefs.py    fallback 16-class taxonomy + reading class options from a project's JSON
  utils.py        shared helpers (natural sort key)
  web/
    index.html    page skeleton with {{STYLE}} / {{SCRIPT}} placeholders + __CLIP_OPTIONS__ / __CLASSES__
    style.css     all styling
    app.js        all client logic (rendering, editing, undo/redo, autosave, compare diff)
```

## How it fits together

- `app.py` discovers clips and starts a `ThreadingHTTPServer` with the handler from `server.py`.
- `server.py` routes: `/` → `render.py` builds the page; `/clipdata`, `/frame`, `/save` → `clip.py`;
  `/ls` → `fsbrowse.py`; `/open`, `/validate` → `compare.py` + `clip.py`.
- `render.py` reads `web/index.html`, injects `web/style.css` and `web/app.js`, and fills the clip
  dropdown + fallback class list. The assembled page is byte-identical to the old monolith's.
- **Non-destructive editing:** saves (manual + autosave) go to a sibling `<name>.edited.json`; the
  original is never written. Class dropdown options come from the opened JSON. Compare highlights only
  boxes present in one file but not the other (matching tracked objects by id, untracked by geometry).

## Notes

- The presentation lives entirely in `web/`; edit `app.js` / `style.css` without touching Python.
- To add a route, add a branch in `server.py` and a handler in the relevant module.
- The class taxonomy fallback in `classdefs.py` mirrors `core/classes.py` — keep them in sync.
