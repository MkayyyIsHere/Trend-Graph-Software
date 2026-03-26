# =============================================================================
# CONFIGURATION MANAGEMENT  (unchanged)
# =============================================================================

import json
import os
from typing import Dict, List
from utils.constants import DEFAULT_DPI

class ConfigManager:
    def __init__(self, config_path: str = None):
        self.config_path = config_path
        self.config = self._load_config()

    def _normalize_chart_size(self, cfg):
        chart = cfg.get('chart', {})
        if 'resolution_px' in chart:
            res = chart['resolution_px']
            dpi = chart.get('dpi', DEFAULT_DPI)
            if dpi > 0:
                chart['figure_size'] = [res[0] / dpi, res[1] / dpi]
            cfg['chart'] = chart
        return cfg

    def _load_config(self):
        if not self.config_path:
            return {}
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path) as f:
                    return self._normalize_chart_size(json.load(f))
            print(f"Warning: {self.config_path} not found")
        except Exception as e:
            print(f"Error loading config: {e}")
        return {}

    def reload(self, config_path: str) -> bool:
        try:
            with open(config_path) as f:
                cfg = self._normalize_chart_size(json.load(f))
            self.config_path = config_path
            self.config = cfg
            return True
        except Exception as e:
            print(f"Error reloading config '{config_path}': {e}")
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
    def is_multi_series(self)            -> bool:
        s = self.config.get('series', None)
        return isinstance(s, list) and len(s) > 1

    def get_series_processor_kwargs(self) -> Dict:
        s = self.get_series_config()
        return {'value_column': s.get('value_column', None),
                'value_column_keywords': s.get('value_column_keywords', ['value'])}

    def get_series_name(self) -> str:
        if self.is_multi_series():
            return ' / '.join(s.get('name', f'Series {i+1}')
                              for i, s in enumerate(self.get_all_series_configs()))
        return self.get_series_config().get('name', 'Series')

    def get_chart_config(self)      -> Dict: return self.config.get('chart', {})
    def get_axis_config(self)       -> Dict: return self.config.get('axis', {})
    def get_grid_config(self)       -> Dict: return self.config.get('grid', {})
    def get_responsive_config(self) -> Dict: return self.config.get('responsive', {})
    def get_subplot_params(self)    -> Dict: return self.config.get('subplot_params', {})


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
        fallback = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
                    "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"]
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
