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

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
DASH_PORT = 8052
DASH_HOST = "127.0.0.1"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DEFAULT_CONFIGS_DIR      = '5_configs'
DEFAULT_AESTHETICS_PATH  = os.path.join(DEFAULT_CONFIGS_DIR, 'charts', 'aesthetics.json')
DEFAULT_GANTT_CONFIG_PATH = 'config_gantt.json'

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