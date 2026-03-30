# =============================================================================
# CONSTANTS
#
# WHERE TO CHANGE THINGS
# ├── fonts, sizes, resolution, background, grid, legend padding
# │     → 5_configs/aesthetics.json
# ├── series colors/names/columns, chart title, axis labels, y/x limits
# │     → 5_configs/charts/<chart_name>.json
# └── port, paths, resolution preset labels
#       → here (constants.py)
# =============================================================================

import os
import sys

# ---------------------------------------------------------------------------
# Runtime root — works correctly in both PyCharm and PyInstaller .exe
#
# When frozen (.exe):  files are extracted to sys._MEIPASS (a temp folder).
#                      The .exe itself sits in 8_dist/ — we use _MEIPASS so
#                      bundled assets (5_configs, 6_templates) are found.
# When running normally in PyCharm: walk up from this file to the repo root.
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    # Inside the .exe — bundled assets live in _MEIPASS
    _RUNTIME_ROOT = sys._MEIPASS
else:
    # In PyCharm — this file is 3_utils/constants.py, so go up two levels
    _RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
DASH_PORT = 8052
DASH_HOST = "127.0.0.1"

# ---------------------------------------------------------------------------
# Paths  (always absolute, safe in both .exe and PyCharm)
# ---------------------------------------------------------------------------
DEFAULT_CONFIGS_DIR       = os.path.join(_RUNTIME_ROOT, '5_configs')
DEFAULT_AESTHETICS_PATH   = os.path.join(DEFAULT_CONFIGS_DIR, 'charts', 'aesthetics.json')
DEFAULT_GANTT_CONFIG_PATH = os.path.join(_RUNTIME_ROOT, '5_configs', 'events', 'config_composite_gantt.json')

# ---------------------------------------------------------------------------
# Resolution presets  (labels only — actual values are tuples for the UI)
# The default resolution lives in aesthetics.json → chart.resolution_px
# ---------------------------------------------------------------------------
RESOLUTION_PRESETS = {
    "Custom":                          None,
    "1280×720 (HD)":                   (1280,  720),
    "1920×1080 (Full HD)":             (1920, 1080),
    "2560×1440 (2K/QHD)  ← default":  (2560, 1440),
    "3840×2160 (4K UHD)":              (3840, 2160),
}

# ---------------------------------------------------------------------------
# Reserved filenames — never treated as chart configs by the batch worker
# or shown in the chart file list in Config Manager.
# ---------------------------------------------------------------------------
RESERVED_CONFIG_FILENAMES = {
    'aesthetics.json',
    'batch_profile.json',
}
DEFAULT_DPI          = 96
DEFAULT_FIGURE_SIZE  = [2560 / DEFAULT_DPI, 1440 / DEFAULT_DPI]