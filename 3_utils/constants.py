# =============================================================================
# CONSTANTS
#
# WHERE TO CHANGE THINGS
# ├── fonts, sizes, resolution, background, grid, legend padding
# │     → user's 5_configs/aesthetics.json  (outside the .exe)
# ├── series colors/names/columns, chart title, axis labels, y/x limits
# │     → user's 5_configs/charts/<chart_name>.json
# └── port, resolution preset labels
#       → here (constants.py)
#
# NOTE ON PATHS
# Default configs, gantt colours and the PPT template are bundled inside the
# .exe under 3_utils/defaults/ (read-only).  Anything the user changes is
# stored in user_data_dir() (%APPDATA%/TrendGraph) so it survives restarts.
# =============================================================================

import json
import os
import sys
import threading

# ---------------------------------------------------------------------------
# Runtime root — works correctly in both PyCharm and PyInstaller .exe
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _RUNTIME_ROOT = sys._MEIPASS
else:
    _RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
DASH_PORT = 8052
DASH_HOST = "127.0.0.1"

# ---------------------------------------------------------------------------
# Bundled defaults (read-only) and user data (writable, persists)
# ---------------------------------------------------------------------------
def resource_path(*parts: str) -> str:
    """Path to a file shipped inside the app (works in dev and in the .exe)."""
    return os.path.join(_RUNTIME_ROOT, '3_utils', 'defaults', *parts)


def user_data_dir() -> str:
    """Writable per-user folder (%APPDATA%/TrendGraph); created on first use."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, 'TrendGraph')
    os.makedirs(path, exist_ok=True)
    return path


_SETTINGS_FILE = 'settings.json'
_SETTINGS_LOCK = threading.Lock()   # Dash callbacks run concurrently


def load_settings() -> dict:
    try:
        with open(os.path.join(user_data_dir(), _SETTINGS_FILE), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(**updates) -> None:
    """Merge `updates` into settings.json (best effort)."""
    with _SETTINGS_LOCK:
        try:
            data = load_settings()
            if all(data.get(k) == v for k, v in updates.items()):
                return
            data.update(updates)
            with open(os.path.join(user_data_dir(), _SETTINGS_FILE), 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


DEFAULT_CONFIGS_DIR       = resource_path('charts')
DEFAULT_AESTHETICS_PATH   = resource_path('charts', 'aesthetics.json')
DEFAULT_GANTT_CONFIG_PATH = resource_path('gantt.json')
DEFAULT_PPT_TEMPLATE_PATH = resource_path('PQA_Template.pptx')


def user_gantt_path() -> str:
    """Event colours edited in Config Manager (overrides the bundled gantt.json)."""
    return os.path.join(user_data_dir(), 'gantt.json')

# ---------------------------------------------------------------------------
# Reserved filenames — never treated as chart configs by the batch worker
# or shown in the chart file list in Config Manager.
# ---------------------------------------------------------------------------
GANTT_FILENAME = 'gantt.json'   # event colours kept with a config folder

RESERVED_CONFIG_FILENAMES = {
    'aesthetics.json',
    'batch_profile.json',
    GANTT_FILENAME,
}
# Charts rendered at once in a batch. All PNGs go through one shared browser
# (backend/renderer.py), so a 2nd worker only overlaps data loading with
# rendering; measured: 1 → ~24 s, 2 → ~15 s, 4 or 8 → no faster (28 images).
BATCH_WORKERS = 2

DEFAULT_DPI          = 96
DEFAULT_FIGURE_SIZE  = [2560 / DEFAULT_DPI, 1440 / DEFAULT_DPI]