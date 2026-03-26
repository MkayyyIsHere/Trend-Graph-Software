import sys
import os
import types

# ---------------------------------------------------------------------------
# Folder alias resolver
# Maps prefixed folder names to importable module names by registering each
# prefixed folder as a package in sys.modules under its original name.
# Must run before any project imports. Works for all submodule imports too
# e.g. "from utils.constants import X" or "from app.dash_app import Y".
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_FOLDER_MAP = {
    "1_app":       "app",
    "2_backend":   "backend",
    "3_utils":     "utils",
    "4_assets":    "assets",
    "5_configs":   "configs",
    "6_templates": "templates",
    "7_samples":   "samples",
}

for _prefixed, _alias in _FOLDER_MAP.items():
    _prefixed_path = os.path.join(_ROOT, _prefixed)
    if os.path.isdir(_prefixed_path) and _alias not in sys.modules:
        _mod = types.ModuleType(_alias)
        _mod.__path__ = [_prefixed_path]   # makes it a package, enables submodule imports
        _mod.__package__ = _alias
        sys.modules[_alias] = _mod

# ---------------------------------------------------------------------------

import argparse

from utils.constants import DASH_PORT
from app.dash_app import DashApp


def main():
    parser = argparse.ArgumentParser(
        description='Composite Data & Gantt Plotter — Dash Edition'
    )
    parser.add_argument('--port',       type=int,            default=DASH_PORT,
                        help=f'Port to serve on (default: {DASH_PORT})')
    parser.add_argument('--debug',      action='store_true', default=False,
                        help='Enable Dash debug / hot-reload mode')
    parser.add_argument('--no-browser', action='store_true', default=False,
                        help='Do not auto-open a browser tab on startup')
    args = parser.parse_args()

    DashApp().run(port=args.port, debug=args.debug, auto_open=not args.no_browser)


if __name__ == '__main__':
    main()