import sys
import os
import types

# ---------------------------------------------------------------------------
# DEBUG BUILD — writes a log file next to the .exe so you can see exactly
# what paths and folders PyInstaller extracted.
# Delete the debug block once the real build works.
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)), "debug_log.txt")

def _log(msg):
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

_log("=" * 60)
_log(f"frozen      : {getattr(sys, 'frozen', False)}")
_log(f"sys.executable : {sys.executable}")
_log(f"__file__    : {__file__}")

if getattr(sys, 'frozen', False):
    _ROOT = sys._MEIPASS
    _log(f"_MEIPASS    : {sys._MEIPASS}")
    _log("Contents of _MEIPASS:")
    for item in sorted(os.listdir(sys._MEIPASS)):
        _log(f"  {item}")
else:
    _ROOT = os.path.dirname(os.path.abspath(__file__))

_log(f"_ROOT       : {_ROOT}")

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
    exists = os.path.isdir(_prefixed_path)
    _log(f"  {_prefixed_path}  exists={exists}")
    if exists and _alias not in sys.modules:
        _mod = types.ModuleType(_alias)
        _mod.__path__ = [_prefixed_path]
        _mod.__package__ = _alias
        sys.modules[_alias] = _mod
        _log(f"    → registered as '{_alias}'")

_log("sys.path entries:")
for p in sys.path:
    _log(f"  {p}")

# ---------------------------------------------------------------------------

import argparse

try:
    from utils.constants import DASH_PORT
    _log("SUCCESS: imported utils.constants")
except Exception as e:
    _log(f"FAILED: utils.constants — {e}")
    raise

try:
    from app.dash_app import DashApp
    _log("SUCCESS: imported app.dash_app")
except Exception as e:
    _log(f"FAILED: app.dash_app — {e}")
    raise


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