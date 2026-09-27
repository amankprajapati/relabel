"""Enables `python3 -m relabel_gui_app`. Delegates to app.main()."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # flat imports work under -m too

from app import main

if __name__ == "__main__":
    main()
