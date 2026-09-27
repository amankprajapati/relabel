"""classdefs.py — where the class list comes from.

Classes are never hard-coded. The list shown in the GUI is the union of:
  1. classes declared in the project's JSON (_via_attributes.region.class.options),
  2. classes actually used by regions in the JSON (so nothing in the data is ever unlisted),
  3. classes passed on the command line with --classes (a comma list or a text file, one per line).
The user can then add, rename or remove classes from the GUI; the list is saved back into the
edited JSON's _via_attributes.
"""
import os


def parse_classes_arg(value):
    """--classes value -> list of class names. Accepts 'a,b,c' or a path to a file with one per line."""
    if not value:
        return []
    if os.path.isfile(value):
        with open(value, encoding="utf-8") as f:
            items = [ln.strip() for ln in f]
    else:
        items = [s.strip() for s in value.split(",")]
    return _unique(i for i in items if i and not i.startswith("#"))


def declared_classes(via):
    """Class labels declared in a VIA project's _via_attributes, in order, or []."""
    try:
        opts = via["_via_attributes"]["region"]["class"]["options"]
        # VIA options is {key: label}; the label is what we show and store
        return [str(v) if v not in (None, "") else str(k) for k, v in opts.items()]
    except (KeyError, TypeError, AttributeError):
        return []


def used_classes(via):
    """Class labels used by any region, sorted naturally."""
    from utils import natkey
    seen = set()
    for v in via.get("_via_img_metadata", {}).values():
        for r in v.get("regions", []):
            c = r.get("region_attributes", {}).get("class")
            if c not in (None, "", "NONE"):
                seen.add(str(c))
    return sorted(seen, key=natkey)


def class_options_of(via):
    """Declared classes first (their order), then any used-but-undeclared ones."""
    return _unique(declared_classes(via) + used_classes(via))


def _unique(items):
    out, seen = [], set()
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
