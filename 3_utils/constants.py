# =============================================================================
# CONSTANTS & CONFIG  (unchanged from original)
# =============================================================================

DEFAULT_GANTT_CONFIG_PATH = 'config_gantt.json'
DEFAULT_FIGURE_SIZE       = [2560 / 96, 1440 / 96]
DEFAULT_DPI               = 96

RESOLUTION_PRESETS = {
    "Custom":                          None,
    "1280×720 (HD)":                   (1280,  720),
    "1920×1080 (Full HD)":             (1920, 1080),
    "2560×1440 (2K/QHD)  ← default":  (2560, 1440),
    "3840×2160 (4K UHD)":              (3840, 2160),
}

DASH_PORT = 8052
DASH_HOST = "127.0.0.1"

# Config Manager defaults
DEFAULT_CONFIGS_DIR = '5_configs'