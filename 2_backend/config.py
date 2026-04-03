# =============================================================================
# CONFIGURATION MANAGEMENT
#
# Loading order (later wins, with logged warnings on aesthetic overrides):
#   1. aesthetics.json  — master visual defaults (fonts, resolution, grid, legend)
#   2. per-chart JSON   — series data, title, axis labels/limits, subplot margins
#
# WHERE TO CHANGE THINGS
# ├── fonts, sizes, resolution, background, grid, legend padding
# │     → 5_configs/aesthetics.json
# ├── series colors/names/columns, chart title, axis labels, y/x limits
# │     → 5_configs/charts/<chart_name>.json
# └── port, paths, resolution preset labels
#       → 3_utils/constants.py
# =============================================================================

import json
import os
from typing import Any, Dict, List, Optional

from utils.constants import DEFAULT_DPI, DEFAULT_AESTHETICS_PATH
from utils.logger import GUILogger


# ---------------------------------------------------------------------------
# Fields that belong exclusively in aesthetics.json.
# If a per-chart JSON contains any of these, a WARNING is logged so you know
# immediately that drift is happening.
# ---------------------------------------------------------------------------
_AESTHETIC_FIELDS = {
    # top-level section → field (None = whole section is aesthetic)
    ('font',    None),
    ('grid',    None),
    ('legend',  None),
    ('chart',   'background_color'),
    ('chart',   'dpi'),
    ('chart',   'resolution_px'),
    ('',        'linewidth_scale_factor'),
}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base. override wins on conflicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _warn_aesthetic_overrides(chart_cfg: Dict, logger: Optional[Any]) -> None:
    """
    Inspect chart_cfg for keys that should live in aesthetics.json.
    Emit a WARNING for each one found so the user knows to consolidate.
    """
    def _warn(msg):
        if logger:
            logger.warning(msg)
        else:
            print(f"[CONFIG WARNING] {msg}")

    for section, field in _AESTHETIC_FIELDS:
        if section == '':
            # top-level key
            if field in chart_cfg:
                _warn(
                    f"Per-chart config overrides aesthetic field '{field}'. "
                    f"Value: {chart_cfg[field]!r}. "
                    f"Move to aesthetics.json to keep settings uniform."
                )
        elif section in chart_cfg:
            sec = chart_cfg[section]
            if isinstance(sec, dict):
                if field is None:
                    # whole section is aesthetic
                    _warn(
                        f"Per-chart config contains entire '{section}' section "
                        f"which belongs in aesthetics.json. "
                        f"Move shared settings there to keep them uniform."
                    )
                elif field in sec:
                    _warn(
                        f"Per-chart config overrides aesthetic field '{section}.{field}'. "
                        f"Value: {sec[field]!r}. "
                        f"Move to aesthetics.json to keep settings uniform."
                    )


class ConfigManager:
    """
    Manages the merged configuration for a single chart.

    Usage
    -----
    ConfigManager(chart_config_path)           # aesthetics auto-discovered
    ConfigManager(chart_config_path, aesthetics_path=..., logger=...)
    """

    def __init__(self,
                 config_path: str = None,
                 aesthetics_path: str = None,
                 logger: Optional[Any] = None):
        self.config_path     = config_path
        self.aesthetics_path = aesthetics_path or DEFAULT_AESTHETICS_PATH
        self.logger          = logger
        self.config          = self._build_config()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_warning(self, msg: str) -> None:
        if self.logger:
            self.logger.warning(msg)
        else:
            print(f"[CONFIG WARNING] {msg}")

    def _load_json(self, path: str, label: str) -> Dict:
        """Load a JSON file, return {} on any failure."""
        if not path:
            return {}
        if not os.path.exists(path):
            self._log_warning(f"{label} not found: {path}")
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            self._log_warning(f"Error loading {label} '{path}': {e}")
            return {}

    def _normalize_chart_size(self, cfg: Dict) -> Dict:
        """Derive figure_size (inches) from resolution_px + dpi."""
        chart = cfg.get('chart', {})
        res   = chart.get('resolution_px')
        dpi   = chart.get('dpi', DEFAULT_DPI)
        if res and dpi > 0:
            chart['figure_size'] = [res[0] / dpi, res[1] / dpi]
            cfg['chart'] = chart
        return cfg

    def _aesthetics_to_internal(self, aes: Dict) -> Dict:
        """
        Translate the flat aesthetics.json structure into the internal shape
        that chart_gen.py and plotly_preview.py expect:
          font      → responsive.*
          legend    → responsive.legend_* + subplot_params.legend_width_px
          chart     → chart.*
          grid      → grid.*
          subplot_params → subplot_params.*
          linewidth_scale_factor → responsive.linewidth_scale_factor
        """
        font    = aes.get('font', {})
        legend  = aes.get('legend', {})
        chart   = dict(aes.get('chart', {}))
        grid    = aes.get('grid', {})
        sp      = aes.get('subplot_params', {})
        lw_sf   = aes.get('linewidth_scale_factor', 1.0)

        responsive = {
            'font_scale_factor':         font.get('scale_factor', 1.0),
            'linewidth_scale_factor':    lw_sf,
            'title_fontsize_base':       font.get('title_size', 20),
            'axis_label_fontsize_base':  font.get('axis_label_size', 15),
            'tick_fontsize_base':        font.get('tick_size', 12),
            'legend_fontsize_base':      font.get('legend_size', 13),
            'legend_font_family':        font.get('family', 'sans-serif'),
            'legend_pad_top':            legend.get('pad_top', 0.5),
            'legend_pad_sep_above':      legend.get('pad_sep_above', 0.4),
            'legend_pad_sep_below':      legend.get('pad_sep_below', 0.4),
            'legend_gap_slots':          legend.get('gap_slots', 0.5),
            'legend_wrap_width':         legend.get('wrap_width', 28),
        }

        subplot_params = dict(sp)
        if 'width_px' in legend:
            subplot_params['legend_width_px'] = legend['width_px']

        return {
            'chart':          chart,
            'grid':           grid,
            'responsive':     responsive,
            'subplot_params': subplot_params,
        }

    def _build_config(self) -> Dict:
        """
        Load aesthetics → translate to internal shape → merge chart config on top.
        Warn on any aesthetic fields found in the per-chart config.
        """
        # 1. Load & translate aesthetics
        aes_raw  = self._load_json(self.aesthetics_path, 'aesthetics config')
        base_cfg = self._aesthetics_to_internal(aes_raw)

        # 2. Load per-chart config
        chart_raw = self._load_json(self.config_path, 'chart config') if self.config_path else {}

        # 3. Warn about aesthetic overrides in the chart config
        if chart_raw:
            _warn_aesthetic_overrides(chart_raw, self.logger)

        # 4. Deep-merge: aesthetics base ← chart overrides
        merged = _deep_merge(base_cfg, chart_raw)

        # 5. Derive figure_size from final merged resolution_px + dpi
        return self._normalize_chart_size(merged)

    # ------------------------------------------------------------------
    # Public API  (unchanged surface — callers need no changes)
    # ------------------------------------------------------------------

    def reload(self, config_path: str) -> bool:
        """Reload the per-chart config (aesthetics are re-applied automatically)."""
        try:
            self.config_path = config_path
            self.config      = self._build_config()
            return True
        except Exception as e:
            self._log_warning(f"Error reloading config '{config_path}': {e}")
            return False

    def reload_aesthetics(self, aesthetics_path: str) -> bool:
        """Hot-reload aesthetics without changing the chart config."""
        try:
            self.aesthetics_path = aesthetics_path
            self.config          = self._build_config()
            return True
        except Exception as e:
            self._log_warning(f"Error reloading aesthetics '{aesthetics_path}': {e}")
            return False

    def get_all_series_configs(self) -> List[Dict]:
        if 'series' in self.config:
            s = self.config['series']
            return s if isinstance(s, list) else [s]
        s = dict(self.config.get('frequency', {}))
        s.setdefault('name', 'Series')
        s.setdefault('value_column', None)
        s.setdefault('value_column_keywords', ['value'])
        return [s]

    def get_series_config(self)          -> Dict: return self.get_all_series_configs()[0]

    def is_multi_series(self) -> bool:
        s = self.config.get('series', None)
        return isinstance(s, list) and len(s) > 1

    def get_series_processor_kwargs(self) -> Dict:
        s = self.get_series_config()
        return {
            'value_column':          s.get('value_column', None),
            'value_column_keywords': s.get('value_column_keywords', ['value']),
        }

    def get_series_name(self) -> str:
        if self.is_multi_series():
            return ' / '.join(
                s.get('name', f'Series {i+1}')
                for i, s in enumerate(self.get_all_series_configs()))
        return self.get_series_config().get('name', 'Series')

    def get_chart_config(self)      -> Dict: return self.config.get('chart', {})
    def get_axis_config(self)       -> Dict: return self.config.get('axis', {})
    def get_grid_config(self)       -> Dict: return self.config.get('grid', {})
    def get_responsive_config(self) -> Dict: return self.config.get('responsive', {})
    def get_subplot_params(self)    -> Dict: return self.config.get('subplot_params', {})


# =============================================================================
# GANTT CONFIG  (unchanged)
# =============================================================================

class GanttConfigManager:
    def __init__(self, config_path: str = None):
        self.config_path = config_path
        self.config      = None
        self.color_index = 0
        if config_path and os.path.exists(config_path):
            self._load(config_path)

    def _load(self, config_path: str) -> bool:
        try:
            with open(config_path) as f:
                data = json.load(f)
            if 'gantt' not in data and 'gantt_colors' not in data:
                print(f"Warning: '{config_path}' has no 'gantt' or 'gantt_colors' section")
                return False
            self.config      = data
            self.config_path = config_path
            self.color_index = 0
            return True
        except Exception as e:
            print(f"Error loading gantt config '{config_path}': {e}")
            return False

    def reload(self, config_path: str) -> bool:
        return self._load(config_path)

    def is_loaded(self) -> bool:
        return self.config is not None

    def get_gantt_config(self) -> Dict:
        return self.config.get('gantt', {}) if self.config else {}

    def get_color_for_test_id(self, test_id: str) -> str:
        fallback = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
        if not self.config:
            color = fallback[self.color_index % len(fallback)]
            self.color_index += 1
            return color
        colors  = self.config.get('gantt_colors', {})
        if test_id in colors:
            return colors[test_id]
        palette = colors.get('default_palette', fallback)
        color   = palette[self.color_index % len(palette)]
        self.color_index += 1
        return color