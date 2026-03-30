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
# 5_configs and 6_templates are NOT bundled inside the .exe.
# The user selects their own config folder at runtime via the app's UI.
# DEFAULT_CONFIGS_DIR and DEFAULT_AESTHETICS_PATH are left as empty strings
# here — the app populates them from the user's folder picker selection.
# =============================================================================

import os
import sys

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
# Paths
#
# These are intentionally empty — the user selects their config folder
# at runtime via the app's folder picker. Any code that needs the config
# path should receive it as a parameter rather than reading these defaults.
#
# In PyCharm (dev mode) you can temporarily set these to your local paths
# for convenience, but do not commit hardcoded paths.
# ---------------------------------------------------------------------------
DEFAULT_CONFIGS_DIR       = ""
DEFAULT_AESTHETICS_PATH   = ""
DEFAULT_GANTT_CONFIG_PATH = ""

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