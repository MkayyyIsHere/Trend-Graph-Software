"""
Composite Data & Gantt Plotter — Dash Web Frontend
====================================================
Drop-in replacement for composite_plotter.py.

All backend classes are IDENTICAL to the original:
    DataPoint, Task, SeriesDataProcessor, EventDataProcessor,
    ConfigManager, GanttConfigManager, GUILogger,
    CompositeChartGenerator, PPTBuilder

Only the GUI shell has been replaced:
    CompositeDataPlotterApp(tk.Tk)  →  DashApp (Dash / Bootstrap)

New features vs the Tkinter version
-------------------------------------
- Interactive Plotly preview (zoom/pan) alongside the Matplotlib export
- Data summary table (rows, time range, value range)
- Event/task preview table
- Batch progress log streamed into the Live Preview tab
- Responsive layout via Bootstrap grid – works in any browser
- File paths still typed/pasted as text (Dash runs locally, so no
  OS file-picker; paths work exactly like the original CLI args)

Usage
------
    python composite_plotter_dash.py
    # then open http://127.0.0.1:8052

Dependencies (new vs original)
-------------------------------
    pip install dash dash-bootstrap-components plotly
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import io
import json
import logging
import os
import platform
import re
import subprocess
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── third-party ───────────────────────────────────────────────────────────────
import pandas as pd

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.shapes import PP_PLACEHOLDER
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

import matplotlib
matplotlib.use('Agg')          # no display needed – we render to bytes
matplotlib.interactive(False)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from matplotlib.patches import Patch  # noqa: F401

import plotly.graph_objects as go
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, dash_table, ctx, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from flask import request as flask_request

# ── base64 helper (for sending Matplotlib PNG into the browser) ───────────────
import base64


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


# =============================================================================
# DATA MODELS  (unchanged)
# =============================================================================

class DataPoint:
    def __init__(self, timestamp: datetime, value: float):
        self.timestamp = timestamp
        self.value     = value


class Task:
    def __init__(self, description: str, test_id: str, start_time: datetime,
                 end_time: datetime, is_normalization: bool = False, row_number: int = 0):
        self.description      = description
        self.test_id          = test_id
        self.start_time       = start_time
        self.end_time         = end_time
        self.is_normalization = is_normalization
        self.row_number       = row_number

    @property
    def display_id(self) -> str:
        return f"{self.test_id} (N)" if self.is_normalization else self.test_id

    @property
    def legend_no(self) -> str:
        return f"{self.row_number}(N)" if self.is_normalization else str(self.row_number)


# =============================================================================
# DATA PROCESSING — Series  (unchanged)
# =============================================================================

class SeriesDataProcessor:
    def __init__(self, logger=None, value_column: str = None,
                 value_column_keywords: List[str] = None):
        self.logger                = logger
        self.value_column          = value_column
        self.value_column_keywords = value_column_keywords or ['value']
        self.data_points: List[DataPoint] = []

    def _log(self, msg: str, level: str = 'INFO'):
        if self.logger:
            getattr(self.logger, level.lower())(msg)

    def _resolve_columns(self, columns) -> bool:
        self._resolved_start_col = next(
            (c for c in columns if 'start' in c.lower()), columns[0] if columns else None)
        self._resolved_value_col = None
        if self.value_column:
            self._resolved_value_col = next(
                (c for c in columns if c.lower() == self.value_column.lower()), None)
            if self._resolved_value_col:
                self._log(f"Value column (exact match): '{self._resolved_value_col}'")
        if self._resolved_value_col is None:
            for kw in self.value_column_keywords:
                self._resolved_value_col = next(
                    (c for c in columns if kw.lower() in c.lower()), None)
                if self._resolved_value_col:
                    self._log(f"Value column (keyword match): '{self._resolved_value_col}'")
                    break
        if self._resolved_value_col is None:
            self._resolved_value_col = columns[-1] if columns else None
            if self._resolved_value_col:
                self._log(f"Value column (fallback, last column): '{self._resolved_value_col}'", 'WARNING')
        if not self._resolved_start_col or not self._resolved_value_col:
            self._log("Could not resolve timestamp or value column", 'ERROR')
            return False
        self._log(f"Timestamp column: '{self._resolved_start_col}'")
        return True

    def _detect_ts_format(self, sample: str) -> Optional[str]:
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S',
                    '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S',
                    '%Y-%m-%d %I:%M:%S %p', '%d/%m/%Y %I:%M:%S %p'):
            try:
                datetime.strptime(sample, fmt)
                return fmt
            except ValueError:
                continue
        return None

    def load_data(self, file_path: str) -> bool:
        try:
            self.data_points = []
            df = None
            for sep in (',', '\t', ';', ' '):
                try:
                    df = pd.read_csv(file_path, sep=sep)
                    if len(df.columns) > 1:
                        self._log(f"Detected delimiter: '{repr(sep)}'")
                        break
                except Exception:
                    continue
            if df is None or len(df.columns) == 1:
                self._log("Could not auto-detect delimiter. Trying default CSV parsing.", 'WARNING')
                df = pd.read_csv(file_path)

            self._log(f"Data file loaded: {file_path}")
            self._log(f"Found {len(df.columns)} columns: {list(df.columns)}")
            self._log(f"Processing {len(df)} rows...")

            if not self._resolve_columns(list(df.columns)):
                return False

            ts_fmt = None
            for val in df[self._resolved_start_col].dropna().astype(str):
                ts_fmt = self._detect_ts_format(val.strip())
                if ts_fmt:
                    self._log(f"Timestamp format detected: '{ts_fmt}'")
                    break

            for idx, row in df.iterrows():
                row_num = idx + 2
                try:
                    start_str = str(row[self._resolved_start_col]).strip()
                    value_str = str(row[self._resolved_value_col]).strip()
                    if not start_str or start_str.lower() == 'nan':
                        continue
                    if not value_str or value_str.lower() == 'nan':
                        continue
                    timestamp = None
                    if ts_fmt:
                        try:
                            timestamp = datetime.strptime(start_str, ts_fmt)
                        except ValueError:
                            pass
                    if timestamp is None:
                        fmt = self._detect_ts_format(start_str)
                        if fmt:
                            timestamp = datetime.strptime(start_str, fmt)
                        else:
                            self._log(f"Row {row_num}: Could not parse timestamp '{start_str}'", 'WARNING')
                            continue
                    try:
                        value = float(value_str)
                    except ValueError:
                        self._log(f"Row {row_num}: Could not parse value '{value_str}'", 'WARNING')
                        continue
                    self.data_points.append(DataPoint(timestamp, value))
                except Exception as e:
                    self._log(f"Row {row_num}: Unexpected error - {e}", 'ERROR')

            self._log(f"Successfully processed {len(self.data_points)} valid data points")
            return True
        except Exception as e:
            self._log(f"Error loading data file: {e}", 'ERROR')
            return False

    def get_data_points(self) -> List[DataPoint]:
        return self.data_points

    def get_summary(self) -> dict:
        if not self.data_points:
            return {'total_points': 0, 'time_range': (None, None), 'value_range': (None, None)}
        timestamps = [dp.timestamp for dp in self.data_points]
        values     = [dp.value     for dp in self.data_points]
        return {
            'total_points': len(self.data_points),
            'time_range':   (min(timestamps), max(timestamps)),
            'value_range':  (min(values),     max(values)),
        }


# =============================================================================
# DATA PROCESSING — Gantt/Event  (unchanged)
# =============================================================================

class EventDataProcessor:
    def __init__(self, logger=None):
        self.logger = logger
        self.tasks: List[Task] = []

    def _log(self, msg: str, level: str = 'INFO'):
        if self.logger:
            getattr(self.logger, level.lower())(msg)

    def load_csv(self, file_path: str) -> bool:
        try:
            self.tasks = []
            df = pd.read_csv(file_path, quotechar='"', quoting=0, engine='python')
            self._log(f"Event file loaded: {file_path}")
            self._log(f"Processing {len(df)} rows from CSV")
            for idx, row in df.iterrows():
                self._process_row(row, idx + 2)
            self._log(f"Successfully processed {len(self.tasks)} valid tasks")
            return True
        except Exception as e:
            self._log(f"Error loading event CSV: {e}", 'ERROR')
            return False

    def _process_row(self, row, row_num: int):
        try:
            description         = str(row.get('Test Description', '')).strip()
            test_id             = str(row.get('Test ID', '')).strip()
            date_str            = str(row.get('Date', '')).strip()
            start_time_str      = str(row.get('Start Time', '')).strip()
            end_time_str        = str(row.get('End Time', '')).strip()
            normalized_time_str = str(row.get('Normalized Time', '')).strip()

            is_normalization = bool(normalized_time_str and normalized_time_str.lower() != 'nan')

            if not description or description.lower() == 'nan':
                self._log(f"Row {row_num}: Missing description, skipping", 'WARNING'); return
            if not test_id or test_id == '-' or test_id.lower() == 'nan':
                test_id = 'UNASSIGNED'
                self._log(f"Row {row_num}: Missing test ID, assigned as 'UNASSIGNED'", 'WARNING')
            if not date_str or date_str.lower() == 'nan':
                self._log(f"Row {row_num}: Missing date, skipping", 'WARNING'); return
            try:
                date_obj = datetime.strptime(date_str, '%d/%m/%Y')
            except ValueError:
                self._log(f"Row {row_num}: Invalid date format '{date_str}', skipping", 'WARNING'); return

            start_time, end_time = self._parse_start_end(date_obj, start_time_str, end_time_str, row_num)
            if start_time and end_time:
                self.tasks.append(Task(description, test_id, start_time, end_time,
                                       is_normalization=False, row_number=row_num - 1))

            if is_normalization:
                norm_start, norm_end = self._parse_duration_range(date_obj, normalized_time_str, row_num)
                if norm_start and norm_end:
                    self.tasks.append(Task(description, test_id, norm_start, norm_end,
                                           is_normalization=True, row_number=row_num - 1))
        except Exception as e:
            self._log(f"Row {row_num}: Unexpected error - {e}", 'ERROR')

    def _parse_start_end(self, date_obj, start_str, end_str, row_num):
        cross_day_re  = re.compile(r'^\d{1,2}/\d{1,2}\s+')
        time_token_re = re.compile(r'(\d{1,2})\s*:\s*(\d{2})\s*(am|pm)', re.IGNORECASE)

        def strip_prefix(s):
            m = cross_day_re.match(s)
            return (s[m.end():], True) if m else (s, False)

        def extract_times(raw):
            return [(int(h), int(m), ap) for h, m, ap in time_token_re.findall(raw)]

        def parse_side(raw):
            if not raw or raw.lower() == 'nan':
                return None, False
            cleaned, cross = strip_prefix(raw)
            tokens = extract_times(cleaned)
            if tokens:
                h, m, ap = tokens[0]
                dt = self._create_datetime(date_obj, h, m, ap)
            else:
                dt = self._parse_time(cleaned, date_obj, row_num)
            if dt and cross:
                dt += timedelta(days=1)
            return dt, cross

        start_time, _ = parse_side(start_str)
        end_time = None
        if end_str and end_str.lower() != 'nan':
            cleaned, cross = strip_prefix(end_str)
            tokens = extract_times(cleaned)
            if tokens:
                h, m, ap = tokens[-1]
                end_time = self._create_datetime(date_obj, h, m, ap)
            else:
                end_time = self._parse_time(cleaned, date_obj, row_num)
            if end_time and cross:
                end_time += timedelta(days=1)

        if start_time and end_time:
            if end_time < start_time:
                end_time += timedelta(days=1)
            return start_time, end_time
        if end_time:
            return end_time - timedelta(minutes=30), end_time
        if start_time:
            return start_time, start_time + timedelta(minutes=30)
        self._log(f"Row {row_num}: Could not parse start/end times, skipping", 'WARNING')
        return None, None

    def _parse_duration_range(self, date_obj, range_str, row_num):
        try:
            cleaned = re.sub(r'[A-Z]+-\d+:\s*', '', range_str.strip())
            times   = re.findall(r'(\d{1,2})\s*:\s*(\d{2})\s*(am|pm|AM|PM)', cleaned)
            if len(times) >= 2:
                st = self._create_datetime(date_obj, int(times[0][0]), int(times[0][1]), times[0][2])
                et = self._create_datetime(date_obj, int(times[1][0]), int(times[1][1]), times[1][2])
                if et < st:
                    et += timedelta(days=1)
                return st, et
            if len(times) == 1:
                et = self._create_datetime(date_obj, int(times[0][0]), int(times[0][1]), times[0][2])
                return et - timedelta(minutes=30), et
        except Exception as e:
            self._log(f"Row {row_num}: Error parsing range '{range_str}': {e}", 'WARNING')
        return None, None

    def _parse_time(self, time_str, date_obj, row_num):
        for fmt in ('%I:%M%p', '%H:%M', '%I:%M %p'):
            try:
                return datetime.combine(date_obj.date(),
                                        datetime.strptime(time_str.strip(), fmt).time())
            except ValueError:
                continue
        self._log(f"Row {row_num}: Could not parse time '{time_str}'", 'WARNING')
        return None

    def _create_datetime(self, date_obj, hour, minute, ampm):
        ampm = ampm.lower()
        if ampm == 'pm' and hour != 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
        return datetime.combine(date_obj.date(), datetime.min.time()).replace(hour=hour, minute=minute)

    def get_tasks(self) -> List[Task]:
        return self.tasks

    def get_summary(self) -> dict:
        if not self.tasks:
            return {'total_tasks': 0, 'test_ids': [], 'date_range': (None, None)}
        test_ids = list(dict.fromkeys(t.test_id for t in self.tasks))
        return {
            'total_tasks': len(self.tasks),
            'test_ids':    test_ids,
            'date_range':  (min(t.start_time for t in self.tasks),
                            max(t.end_time   for t in self.tasks)),
        }


# =============================================================================
# CONFIGURATION MANAGEMENT  (unchanged)
# =============================================================================

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


# =============================================================================
# LOGGER  (adapted: callback is a thread-safe list append)
# =============================================================================

class GUILogger:
    _LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}

    def __init__(self, callback=None):
        self.callback = callback
        self._logger  = logging.getLogger('CompositeDataPlotter')
        self._logger.setLevel(logging.DEBUG)
        if not self._logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                             datefmt='%Y-%m-%d %H:%M:%S'))
            self._logger.addHandler(h)

    def log(self, level: str, message: str):
        getattr(self._logger, level.lower())(message)
        if self.callback:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.callback(f"[{ts}] {level}: {message}")

    def debug(self,    msg): self.log('DEBUG',    msg)
    def info(self,     msg): self.log('INFO',     msg)
    def warning(self,  msg): self.log('WARNING',  msg)
    def error(self,    msg): self.log('ERROR',    msg)
    def critical(self, msg): self.log('CRITICAL', msg)


# =============================================================================
# CHART GENERATION  (unchanged — Matplotlib backend)
# =============================================================================

class CompositeChartGenerator:
    def __init__(self, config: ConfigManager, logger: GUILogger = None,
                 gantt_config: GanttConfigManager = None):
        self.config       = config
        self.gantt_config = gantt_config
        self.logger       = logger
        self.fig = self.ax = None
        self.task_colors: Dict[str, str] = {}

    def _log(self, msg, level='INFO'):
        if self.logger:
            getattr(self.logger, level.lower())(msg)

    def _scale_fontsize(self, base):
        f = self.config.get_responsive_config().get('font_scale_factor', 1.0)
        return max(6.0, min(32.0, base * f))

    def _scale_linewidth(self, base):
        f = self.config.get_responsive_config().get('linewidth_scale_factor', 1.0)
        return max(0.5, min(4.0, base * f))

    def generate(self, data_points, tasks: List[Task], output_path: str = None) -> bool:
        try:
            self._log("Starting composite chart generation...")
            all_series = ([data_points] if (data_points and isinstance(data_points[0], DataPoint))
                          else data_points)
            flat_points = [dp for pts in all_series for dp in pts]
            if not flat_points:
                self._log("No data points to plot", 'ERROR')
                return False

            self._setup_figure()
            self._plot_all_series(all_series)

            if self.gantt_config and self.gantt_config.is_loaded():
                self._plot_gantt_events(tasks, flat_points)
            else:
                self._log("No Gantt config loaded — event overlay skipped.", 'WARNING')

            self._configure_appearance(flat_points, tasks)

            if output_path:
                plt.tight_layout()
                self._save_chart(output_path)

            self._log("Composite chart generated successfully")
            return True
        except Exception as e:
            self._log(f"Failed to generate chart: {e}", 'ERROR')
            self._log(traceback.format_exc(), 'ERROR')
            return False

    def _setup_figure(self):
        cc       = self.config.get_chart_config()
        fig_size = cc.get('figure_size', DEFAULT_FIGURE_SIZE)
        dpi      = cc.get('dpi', DEFAULT_DPI)
        self.fig, self.ax = plt.subplots(figsize=fig_size, dpi=dpi)
        self.fig.patch.set_facecolor(cc.get('background_color', '#ffffff'))
        self._log(f"Figure created: {fig_size[0]:.2f}×{fig_size[1]:.2f} in, DPI: {dpi}")

    def _plot_all_series(self, all_series_data):
        all_configs = self.config.get_all_series_configs()
        for idx, data_points in enumerate(all_series_data):
            sc        = all_configs[idx] if idx < len(all_configs) else all_configs[-1]
            name      = sc.get('name', f'Series {idx + 1}')
            color     = sc.get('line_color', '#1f77b4')
            linewidth = self._scale_linewidth(sc.get('linewidth', 1.5))
            linestyle = sc.get('linestyle', '-')
            alpha     = sc.get('alpha', 0.65)
            if not data_points:
                continue
            sorted_pts = sorted(data_points, key=lambda dp: dp.timestamp)
            segments, seg = [], []
            for dp in sorted_pts:
                if seg and (dp.timestamp - seg[-1].timestamp).total_seconds() > 2.0:
                    segments.append(seg); seg = []
                seg.append(dp)
            if seg:
                segments.append(seg)
            for i, segment in enumerate(segments):
                self.ax.plot(
                    [dp.timestamp for dp in segment],
                    [dp.value     for dp in segment],
                    color=color, linewidth=linewidth, linestyle=linestyle,
                    alpha=alpha, label=name if i == 0 else '',
                    marker='', markersize=0, zorder=3)
        self._log(f"Plotted {len(all_series_data)} series total")

    def _entity_x_extent(self, text_artist, start_num, end_num, renderer=None):
        try:
            if renderer is None:
                renderer = self.fig.canvas.get_renderer()
            bbox     = text_artist.get_window_extent(renderer=renderer)
            inv      = self.ax.transData.inverted()
            bl = inv.transform((bbox.x0, bbox.y0))
            tr = inv.transform((bbox.x1, bbox.y1))
            tx0, tx1 = min(bl[0], tr[0]), max(bl[0], tr[0])
            x0 = min(tx0, start_num)
            x1 = max(tx1, end_num)
            n_chars = max(1, len(text_artist.get_text()))
            pad = (tx1 - tx0) / n_chars * 0.5
            return x0 - pad, x1 + pad
        except Exception:
            pad = (end_num - start_num) * 0.02
            return start_num - pad, end_num + pad

    def _entity_y_height(self, text_artist, renderer=None):
        try:
            if renderer is None:
                renderer = self.fig.canvas.get_renderer()
            bbox     = text_artist.get_window_extent(renderer=renderer)
            inv      = self.ax.transData.inverted()
            bl = inv.transform((bbox.x0, bbox.y0))
            tr = inv.transform((bbox.x0, bbox.y1))
            return abs(tr[1] - bl[1])
        except Exception:
            return 0.0

    def _plot_gantt_events(self, tasks, data_points):
        if not tasks or not data_points:
            return
        self._log(f"Plotting {len(tasks)} event tasks...")
        axis_cfg  = self.config.get_axis_config()
        y_min_cfg = axis_cfg.get('y_min', None)
        y_max_cfg = axis_cfg.get('y_max', None)
        if y_min_cfg is not None and y_max_cfg is not None:
            data_min, data_max = float(y_min_cfg), float(y_max_cfg)
        else:
            vals = [dp.value for dp in data_points]
            data_min, data_max = min(vals), max(vals)
        data_range = data_max - data_min
        gantt_cfg  = self.gantt_config.get_gantt_config()
        bar_alpha  = gantt_cfg.get('bar_alpha', 0.25)
        edge_width = self._scale_linewidth(gantt_cfg.get('edge_width', 0.5))
        label_fs   = self._scale_fontsize(
            self.config.get_responsive_config().get('legend_fontsize_base', 10) * 0.85)

        task_data = []
        for task in tasks:
            sn    = mdates.date2num(task.start_time)
            en    = mdates.date2num(task.end_time)
            color = self.gantt_config.get_color_for_test_id(task.test_id)
            self.task_colors[task.test_id] = color
            fc    = color + '40' if not task.is_normalization else '#80808040'
            ec    = color        if not task.is_normalization else '#808080'
            self.ax.axvspan(task.start_time, task.end_time,
                            alpha=bar_alpha, color=color if not task.is_normalization else '#808080',
                            linewidth=edge_width, zorder=1)
            task_data.append({'task': task, 'sn': sn, 'en': en,
                               'color': color if not task.is_normalization else '#808080'})

        placed: List[Tuple[float, float, float, float]] = []
        arrow_lw = self._scale_linewidth(gantt_cfg.get('arrow_linewidth', 0.8))
        arrow_ms = max(6, self._scale_fontsize(6))

        # ── Single canvas draw to initialise the renderer ─────────────────────
        # All subsequent text-measurement calls reuse this cached renderer,
        # eliminating the 2×N full redraws that were the main bottleneck.
        self.fig.canvas.draw()
        renderer = self.fig.canvas.get_renderer()

        # ── Pass 1: measure text height once with invisible probes ────────────
        # Place all probes, measure in one batch, then remove them.
        probes = []
        for td in task_data:
            p = self.ax.text(td['sn'], data_max, td['task'].display_id,
                             fontsize=label_fs, fontweight='bold', alpha=0)
            probes.append(p)

        txt_heights = []
        for p in probes:
            h = self._entity_y_height(p, renderer=renderer)
            txt_heights.append(max(h, data_range * 0.04))
        for p in probes:
            p.remove()

        # ── Pass 2: label placement + final annotation ────────────────────────
        for td, txt_h in zip(task_data, txt_heights):
            sn, en, color = td['sn'], td['en'], td['color']

            label_y  = data_max
            max_tries = 50
            step     = txt_h * 1.1
            px0, px1 = sn, en
            for _ in range(max_tries):
                overlap = False
                for (ex0, ex1, ey0, ey1) in placed:
                    if not (px1 < ex0 or px0 > ex1):
                        if not (label_y + txt_h < ey0 or label_y > ey1):
                            overlap = True
                            break
                if not overlap:
                    break
                label_y -= step

            # Measure x-extent with cached renderer — no extra canvas.draw()
            probe2 = self.ax.text(sn, label_y, td['task'].display_id,
                                  fontsize=label_fs, fontweight='bold', alpha=0)
            rx0, rx1 = self._entity_x_extent(probe2, sn, en, renderer=renderer)
            probe2.remove()
            placed.append((rx0, rx1, label_y, label_y + txt_h))

            arrow_y = label_y + txt_h * 0.5
            self.ax.annotate('', xy=(en, arrow_y), xytext=(sn, arrow_y),
                             arrowprops=dict(arrowstyle='<->', color=color, lw=arrow_lw,
                                            linestyle='dotted', mutation_scale=arrow_ms),
                             zorder=5, annotation_clip=True)
            self.ax.text(sn, label_y, td['task'].display_id, color=color,
                         fontsize=label_fs, fontweight='bold', va='bottom', ha='left',
                         clip_on=True, zorder=6,
                         bbox=dict(boxstyle='round,pad=0.15', facecolor='white',
                                   edgecolor=color, alpha=0.75, linewidth=0.5))

        self._log(f"Plotted {len(tasks)} Gantt bars")

    def _configure_appearance(self, data_points, tasks):
        cc  = self.config.get_chart_config()
        ac  = self.config.get_axis_config()
        rc  = self.config.get_responsive_config()
        gc  = self.config.get_grid_config()
        sp  = self.config.get_subplot_params()

        title_fs = self._scale_fontsize(rc.get('title_fontsize_base', 16))
        label_fs = self._scale_fontsize(rc.get('axis_label_fontsize_base', 12))
        tick_fs  = self._scale_fontsize(rc.get('tick_fontsize_base', 10))

        self.fig.text(0.5, 0.98, cc.get('title', 'Data Over Time with Events'),
                      fontsize=title_fs, fontweight='bold', ha='center', va='top',
                      transform=self.fig.transFigure)

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%I:%M %p\n%b %d'))
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.xaxis.set_minor_locator(mdates.HourLocator())
        self.fig.text(0.5, 0.01, ac.get('x_label', 'Date & Time'),
                      fontsize=label_fs, fontweight='bold', ha='center', va='bottom',
                      transform=self.fig.transFigure)
        self.ax.set_ylabel(ac.get('y_label', 'Value'), fontsize=label_fs, fontweight='bold')

        if (ymi := ac.get('y_major_interval')) is not None:
            self.ax.yaxis.set_major_locator(ticker.MultipleLocator(ymi))
        self.ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))

        y_min, y_max = ac.get('y_min'), ac.get('y_max')
        if y_min is not None and y_max is not None:
            self.ax.set_ylim(y_min, y_max)
        elif y_min is not None:
            self.ax.set_ylim(bottom=y_min)
        elif y_max is not None:
            self.ax.set_ylim(top=y_max)

        x_min_cfg, x_max_cfg = ac.get('x_min'), ac.get('x_max')
        if x_min_cfg and x_max_cfg:
            try:
                self.ax.set_xlim(
                    mdates.date2num(datetime.strptime(x_min_cfg, '%Y-%m-%d %H:%M:%S')),
                    mdates.date2num(datetime.strptime(x_max_cfg, '%Y-%m-%d %H:%M:%S')))
                x_min_cfg = True
            except (ValueError, TypeError):
                x_min_cfg = None
        if not x_min_cfg:
            pts = ([dp.timestamp for dp in data_points] +
                   [t for task in tasks for t in (task.start_time, task.end_time)])
            if pts:
                lo, hi  = min(pts), max(pts)
                padding = max((hi - lo) * 0.05, timedelta(seconds=1))
                self.ax.set_xlim(mdates.date2num(lo - padding), mdates.date2num(hi + padding))

        plt.setp(self.ax.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=tick_fs)
        self.ax.tick_params(axis='x', which='major', length=6, width=1.0, direction='out')
        self.ax.tick_params(axis='x', which='minor', length=3, width=0.7, direction='out')
        self.ax.tick_params(axis='y', which='major', labelsize=tick_fs, length=6, width=1.0, direction='out')
        self.ax.tick_params(axis='y', which='minor', length=3, width=0.7, direction='out')

        for spine in ['left', 'right', 'top']:
            self.ax.spines[spine].set_visible(False)

        if gc.get('visible', True):
            grid_kw = dict(linestyle=gc.get('linestyle', '-'),
                           alpha=gc.get('alpha', 0.25),
                           color=gc.get('color', '#505050'), zorder=0)
            self.ax.grid(True, axis=gc.get('axis', 'both'),
                         linewidth=gc.get('gridwidth', 1), **grid_kw)
            self.ax.grid(True, which='minor', axis='y', linestyle=':', linewidth=0.5,
                         alpha=gc.get('alpha', 0.25) * 0.5,
                         color=gc.get('color', '#505050'), zorder=0)

        legend_width_px = sp.get('legend_width_px', None)
        if legend_width_px is not None:
            fig_w_px = cc.get('figure_size', DEFAULT_FIGURE_SIZE)[0] * cc.get('dpi', DEFAULT_DPI)
            derived  = max(0.0, min(0.99, (fig_w_px - legend_width_px) / fig_w_px))
            self.config.config.setdefault('subplot_params', {})['right']    = derived
            self.config.config['subplot_params']['legend_x'] = derived
            sp = self.config.get_subplot_params()

        left   = max(0.01, min(0.5,  sp.get('left',   0.025)))
        right  = max(0.5,  min(0.99, sp.get('right',  0.92)))
        top    = max(0.5,  min(0.99, sp.get('top',    0.95)))
        bottom = max(0.01, min(0.5,  sp.get('bottom', 0.05)))
        try:
            self.fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom)
        except ValueError:
            pass

        self.fig.canvas.draw()
        gl = self.ax.get_ygridlines()
        if gl:
            gl[0].set_visible(False)

        self._create_legend(tasks)

    def _create_legend(self, tasks):
        import textwrap
        from matplotlib.font_manager import FontProperties

        rc        = self.config.get_responsive_config()
        legend_fs = self._scale_fontsize(rc.get('legend_fontsize_base', 10))
        font_fam  = rc.get('legend_font_family', 'sans-serif')
        sp        = self.config.get_subplot_params()

        legend_x = max(0.0,  min(0.99, sp.get('legend_x', 0.92)))
        top_f    = max(0.5,  min(0.99, sp.get('top',      0.95)))
        bottom_f = max(0.01, min(0.5,  sp.get('bottom',   0.05)))
        legend_y = max(0.0,  min(0.99, sp.get('legend_y', 0.81)))

        leg_ax_w = 1.0 - legend_x
        leg_ax_h = top_f - bottom_f
        if leg_ax_w < 0.01 or leg_ax_h < 0.01:
            return

        leg_ax = self.fig.add_axes([legend_x, bottom_f, leg_ax_w, leg_ax_h])
        leg_ax.set_xlim(0, 1)
        leg_ax.set_ylim(0, 1)
        leg_ax.axis('off')

        PAD_TOP       = rc.get('legend_pad_top',       0.5)
        PAD_SEP_ABOVE = rc.get('legend_pad_sep_above', 0.4)
        PAD_SEP_BELOW = rc.get('legend_pad_sep_below', 0.4)
        GAP_SLOTS     = rc.get('legend_gap_slots',     0.5)
        col_tid_w     = 0.30
        col_desc_x    = col_tid_w + 0.04
        pad_x         = 0.03
        legend_wrap_w = max(10, int((1.0 - col_desc_x - pad_x) / (legend_fs * 0.012)))

        fp_bold   = FontProperties(family=font_fam, size=legend_fs, weight='bold')
        fp_normal = FontProperties(family=font_fam, size=legend_fs, weight='normal')

        def _text(ax, x, y, txt, fp, color='#1a1a1a'):
            ax.text(x, y, txt, transform=ax.transAxes, fontproperties=fp,
                    color=color, va='center', ha='left', clip_on=False)

        all_configs = self.config.get_all_series_configs()
        n_series    = len(all_configs)
        slot_h_frac = legend_fs / (self.fig.get_size_inches()[1] * self.config.get_chart_config().get('dpi', DEFAULT_DPI))
        slot_h      = max(0.02, slot_h_frac * 1.4)

        anchor_y = 1.0 - PAD_TOP * slot_h

        for i, sc in enumerate(all_configs):
            sname = sc.get('name', f'Series {i+1}')
            color = sc.get('line_color', '#1f77b4')
            cy    = anchor_y - i * slot_h - slot_h * 0.5
            leg_ax.plot([pad_x, pad_x + col_tid_w * 0.7], [cy, cy],
                        color=color, linewidth=self._scale_linewidth(1.5),
                        transform=leg_ax.transAxes, clip_on=False)
            _text(leg_ax, pad_x + col_tid_w * 0.75, cy, sname, fp_bold, color)

        sep_y = anchor_y - n_series * slot_h - PAD_SEP_ABOVE * slot_h
        leg_ax.plot([pad_x, 0.97], [sep_y, sep_y],
                    color='#cccccc', linewidth=0.5,
                    transform=leg_ax.transAxes, clip_on=False)

        table_rows = list(dict.fromkeys(
            (t.display_id, t.description) for t in tasks))
        wrapped = [textwrap.wrap(desc or '', width=legend_wrap_w) or ['']
                   for _, desc in table_rows]

        cursor_slot = PAD_SEP_BELOW
        for j, ((display_id, _), lines) in enumerate(zip(table_rows, wrapped)):
            n_lines      = len(lines)
            first_line_cy = sep_y - (cursor_slot + 0.5) * slot_h
            _text(leg_ax, pad_x, first_line_cy, display_id, fp_bold)
            for k, ln in enumerate(lines):
                line_cy = sep_y - (cursor_slot + k + 0.5) * slot_h
                _text(leg_ax, col_desc_x, line_cy, ln, fp_normal)
            cursor_slot += n_lines + GAP_SLOTS

    def _save_chart(self, output_path: str):
        try:
            self.fig.savefig(output_path,
                             dpi=self.config.get_chart_config().get('dpi', DEFAULT_DPI),
                             bbox_inches=None, facecolor='white', edgecolor='none', pad_inches=0)
            self._log(f"Chart saved to: {output_path}")
        except Exception as e:
            self._log(f"Failed to save chart: {e}", 'ERROR')

    def to_png_bytes(self) -> bytes:
        """Return the current figure as PNG bytes (for browser display)."""
        buf = io.BytesIO()
        self.fig.savefig(buf, format='png',
                         dpi=self.config.get_chart_config().get('dpi', DEFAULT_DPI),
                         bbox_inches=None, facecolor='white', edgecolor='none', pad_inches=0)
        buf.seek(0)
        return buf.read()


# =============================================================================
# PPT BUILDER  (unchanged)
# =============================================================================

class PPTBuilder:
    IMAGE_EXTS = {'.png', '.jpg', '.jpeg'}

    class NoPicturePlaceholderError(Exception):
        pass

    def __init__(self, logger=None):
        self.logger = logger

    def _log(self, msg, level='INFO'):
        if self.logger:
            getattr(self.logger, level.lower())(msg)
        else:
            print(f"[{level}] {msg}")

    def collect_images(self, image_folder):
        entries = []
        for fname in os.listdir(image_folder):
            if os.path.splitext(fname)[1].lower() in self.IMAGE_EXTS:
                full = os.path.join(image_folder, fname)
                entries.append((os.path.getmtime(full), fname))
        entries.sort(key=lambda x: (x[0], x[1]))
        return [e[1] for e in entries]

    def find_best_layout(self, prs):
        if not _PPTX_AVAILABLE:
            return None
        title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
        pic_types   = {PP_PLACEHOLDER.PICTURE}
        obj_types   = {PP_PLACEHOLDER.OBJECT}
        body_types  = {PP_PLACEHOLDER.BODY}
        candidates  = {1: None, 2: None, 3: None, 4: None}
        for layout in prs.slide_layouts:
            ph_types  = {ph.placeholder_format.type for ph in layout.placeholders
                         if ph.placeholder_format}
            has_title = bool(ph_types & title_types)
            if not has_title:
                continue
            if candidates[1] is None and ph_types & pic_types:  candidates[1] = layout
            if candidates[2] is None and ph_types & obj_types:   candidates[2] = layout
            if candidates[3] is None and ph_types & body_types:  candidates[3] = layout
            if candidates[4] is None:                            candidates[4] = layout
        chosen = candidates[1] or candidates[2] or candidates[3] or candidates[4]
        if chosen:
            self._log(f"Selected layout: '{chosen.name}'")
        return chosen

    def validate_layout_has_picture(self, layout) -> bool:
        if layout is None:
            return False
        title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
        for ph in layout.placeholders:
            if ph.placeholder_format and ph.placeholder_format.type not in title_types:
                return True
        return False

    def _find_title_ph(self, slide):
        title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
        for ph in slide.placeholders:
            if ph.placeholder_format and ph.placeholder_format.type in title_types:
                return ph
        return None

    def _find_picture_ph(self, slide):
        title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
        pic_order   = {PP_PLACEHOLDER.PICTURE: 0, PP_PLACEHOLDER.OBJECT: 1, PP_PLACEHOLDER.BODY: 2}
        best_ph, best_score = None, 99
        for ph in slide.placeholders:
            pf = ph.placeholder_format
            if not pf or pf.type in title_types:
                continue
            score = pic_order.get(pf.type, 3)
            if score < best_score:
                best_score = score
                best_ph    = ph
        return best_ph

    @staticmethod
    def _image_px(image_path):
        try:
            from PIL import Image as PILImage
            with PILImage.open(image_path) as img:
                return img.size
        except Exception:
            return (1920, 1080)

    @staticmethod
    def _resize_slide_canvas(prs, width_px, height_px, dpi=96):
        emu_per_inch     = 914400
        prs.slide_width  = int(width_px  / dpi * emu_per_inch)
        prs.slide_height = int(height_px / dpi * emu_per_inch)

    def _insert_image_auto_resize(self, slide, prs, image_path, img_w, img_h, dpi=96):
        self._resize_slide_canvas(prs, img_w, img_h, dpi)
        pic_ph = self._find_picture_ph(slide)
        if pic_ph:
            try:
                pic_ph._element.getparent().remove(pic_ph._element)
            except Exception:
                pass
        slide.shapes.add_picture(image_path, 0, 0, prs.slide_width, prs.slide_height)

    def _insert_image_in_placeholder(self, slide, ph, image_path, img_w, img_h):
        ph_left, ph_top   = ph.left,  ph.top
        ph_width, ph_height = ph.width, ph.height
        if img_w > 0 and img_h > 0:
            scale = min(ph_width / img_w, ph_height / img_h)
            new_w, new_h = int(img_w * scale), int(img_h * scale)
        else:
            new_w, new_h = ph_width, ph_height
        left = ph_left + (ph_width  - new_w) // 2
        top  = ph_top  + (ph_height - new_h) // 2
        try:
            ph._element.getparent().remove(ph._element)
        except Exception:
            pass
        slide.shapes.add_picture(image_path, left, top, new_w, new_h)

    def build(self, image_folder, template_path, output_path,
              auto_resize_slide=True, slide_dpi=96,
              layout_index=None, progress_callback=None):
        if not _PPTX_AVAILABLE:
            self._log("python-pptx not installed.", 'ERROR')
            return None
        images = self.collect_images(image_folder)
        if not images:
            self._log(f"No PNG/JPG images found in: {image_folder}", 'ERROR')
            return None
        try:
            prs = Presentation(template_path)
        except Exception as e:
            self._log(f"Failed to load template: {e}", 'ERROR')
            return None

        layout = None
        if layout_index is not None:
            try:
                layout = prs.slide_layouts[layout_index]
            except IndexError:
                pass
        if layout is None:
            layout = self.find_best_layout(prs) or prs.slide_layouts[0]

        if not auto_resize_slide and not self.validate_layout_has_picture(layout):
            raise PPTBuilder.NoPicturePlaceholderError(
                f"Template layout '{layout.name}' has no picture placeholder.")

        for idx, filename in enumerate(images):
            image_path = os.path.join(image_folder, filename)
            if progress_callback:
                progress_callback(idx + 1, len(images), filename)
            try:
                img_w, img_h = self._image_px(image_path)
                slide        = prs.slides.add_slide(layout)
                title_ph     = self._find_title_ph(slide)
                if title_ph:
                    title_ph.text = os.path.splitext(filename)[0]
                if auto_resize_slide:
                    self._insert_image_auto_resize(slide, prs, image_path, img_w, img_h, slide_dpi)
                else:
                    pic_ph = self._find_picture_ph(slide)
                    if pic_ph:
                        self._insert_image_in_placeholder(slide, pic_ph, image_path, img_w, img_h)
                self._log(f"  [{idx+1}/{len(images)}] '{filename}'  ({img_w}×{img_h} px)")
            except Exception as e:
                self._log(f"  [{idx+1}] ERROR processing '{filename}': {e}", 'ERROR')

        try:
            prs.save(output_path)
            self._log(f"PPTX saved: {output_path}")
            return output_path
        except Exception as e:
            self._log(f"Failed to save PPTX: {e}", 'ERROR')
            return None


# =============================================================================
# FILENAME HELPER  (unchanged)
# =============================================================================

def _build_output_filename(data_path: str, cfg_path: str) -> str:
    data_stem = os.path.splitext(os.path.basename(data_path))[0]
    cfg_stem  = os.path.splitext(os.path.basename(cfg_path))[0]
    safe      = re.sub(r'[^\w\-_]', '_', f"{data_stem}__{cfg_stem}")
    return f"{safe}.png"


# =============================================================================
# PLOTLY PREVIEW BUILDER  (faithful translation of the Matplotlib chart)
# =============================================================================

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' to 'rgba(r,g,b,alpha)'."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'


def build_plotly_preview(config: ConfigManager,
                         all_series_data: List[List[DataPoint]],
                         tasks: List[Task],
                         gantt_config: GanttConfigManager = None) -> go.Figure:
    """
    Build an interactive Plotly version of the composite chart that faithfully
    mirrors the Matplotlib export:
      • Colored vertical bands for every task
      • Bidirectional arrows (◄►) at label height spanning start→end
      • Collision-free Test ID labels stacked top-down (same algorithm as mpl)
      • Right-side legend table:
            ─ series color swatch + name
            ─ separator
            ─ Test ID (bold) | Description (normal)
    """
    import textwrap as _textwrap

    fig = go.Figure()
    ac      = config.get_axis_config()
    cc      = config.get_chart_config()
    rc      = config.get_responsive_config()
    all_cfg = config.get_all_series_configs()

    # ── Y-axis data range ────────────────────────────────────────────────────
    y_min_cfg = ac.get('y_min')
    y_max_cfg = ac.get('y_max')
    flat_points: List[DataPoint] = [dp for pts in all_series_data for dp in pts]
    if y_min_cfg is not None and y_max_cfg is not None:
        data_min, data_max = float(y_min_cfg), float(y_max_cfg)
    elif flat_points:
        vals = [dp.value for dp in flat_points]
        data_min, data_max = min(vals), max(vals)
    else:
        data_min, data_max = 0.0, 1.0
    data_range = data_max - data_min or 1.0

    # ── Series lines ─────────────────────────────────────────────────────────
    for idx, data_points in enumerate(all_series_data):
        if not data_points:
            continue
        sc        = all_cfg[idx] if idx < len(all_cfg) else all_cfg[-1]
        name      = sc.get('name', f'Series {idx + 1}')
        color     = sc.get('line_color', '#1f77b4')
        linewidth = sc.get('linewidth', 1.5)
        alpha     = sc.get('alpha', 0.65)
        sorted_pts = sorted(data_points, key=lambda dp: dp.timestamp)

        segments, seg = [], []
        for dp in sorted_pts:
            if seg and (dp.timestamp - seg[-1].timestamp).total_seconds() > 2.0:
                segments.append(seg); seg = []
            seg.append(dp)
        if seg:
            segments.append(seg)

        first = True
        for segment in segments:
            fig.add_trace(go.Scatter(
                x=[dp.timestamp for dp in segment],
                y=[dp.value     for dp in segment],
                mode='lines',
                name=name if first else None,
                showlegend=first,
                legendgroup=name,
                line=dict(color=color, width=linewidth),
                opacity=alpha,
                hovertemplate='%{x|%H:%M:%S %b %d}<br>%{y:.4f}<extra>' + name + '</extra>',
            ))
            first = False

    # ── Gantt overlay ─────────────────────────────────────────────────────────
    fallback_palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
    task_colors: Dict[str, str] = {}
    color_idx = 0

    if tasks and gantt_config and gantt_config.is_loaded():
        # reset color counter so colors are assigned fresh (same as mpl)
        gantt_config.color_index = 0

    # Assign colors & collect task data
    task_data = []
    for task in tasks:
        if gantt_config and gantt_config.is_loaded():
            color = gantt_config.get_color_for_test_id(task.test_id)
        else:
            if task.test_id not in task_colors:
                task_colors[task.test_id] = fallback_palette[color_idx % len(fallback_palette)]
                color_idx += 1
            color = task_colors[task.test_id]

        if task.is_normalization:
            fill_rgba = 'rgba(128,128,128,0.08)'
            edge_rgba = 'rgba(128,128,128,0.35)'
            color     = '#808080'
        else:
            fill_rgba = _hex_to_rgba(color, 0.18)
            edge_rgba = _hex_to_rgba(color, 0.70)

        task_data.append({
            'task': task, 'color': color,
            'fill': fill_rgba, 'edge': edge_rgba,
        })

        # Colored band (below data lines)
        fig.add_vrect(
            x0=task.start_time, x1=task.end_time,
            fillcolor=fill_rgba,
            line=dict(color=edge_rgba, width=1),
            layer='below',
        )

    # ── Collision-free label rows (mirrors matplotlib algorithm) ─────────────
    #
    # We work in data-units for Y, datetime for X.
    # Rows stack downward from (data_max - 3 % gap).
    # X-collision is checked in timestamp seconds (no renderer needed in Plotly).
    #
    label_fs   = rc.get('legend_fontsize_base', 10) * 0.85
    # Estimate row height as a fraction of data range (same cap logic as mpl)
    _t         = max(0.0, min(1.0, (data_range - 1.0) / (5000.0 - 1.0)))
    cap_pct    = 0.06 * (1 - _t) + 0.03 * _t
    row_step   = data_range * cap_pct

    base_y     = data_max - data_range * 0.03

    # Estimate character width in seconds to detect X overlaps
    # Use a rough approximation: 1 char ≈ label_fs * 0.5 px, figure is ~2560 px wide
    # Map pixel width to time using x_range
    x_min_dt, x_max_dt = None, None
    if ac.get('x_min') and ac.get('x_max'):
        try:
            x_min_dt = datetime.strptime(ac['x_min'], '%Y-%m-%d %H:%M:%S')
            x_max_dt = datetime.strptime(ac['x_max'], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            pass
    if x_min_dt is None and flat_points:
        all_ts = [dp.timestamp for dp in flat_points]
        x_min_dt, x_max_dt = min(all_ts), max(all_ts)

    if x_min_dt and x_max_dt:
        total_secs = max((x_max_dt - x_min_dt).total_seconds(), 1)
    else:
        total_secs = 86400

    # Rough char width in seconds (label_fs px out of 1200 px plot width)
    char_width_sec = total_secs * (label_fs * 0.6) / 1200.0

    row_slots: Dict[int, List[Tuple[float, float]]] = {}
    assigned_rows = []
    extents_sec   = []  # (x0_sec, x1_sec) per task

    epoch = x_min_dt or datetime(2000, 1, 1)

    for td in task_data:
        task  = td['task']
        s_sec = (task.start_time - epoch).total_seconds()
        e_sec = (task.end_time   - epoch).total_seconds()
        lbl   = task.display_id
        lbl_w = len(lbl) * char_width_sec
        x0_s  = min(s_sec, s_sec)            # label starts at task start
        x1_s  = max(e_sec, s_sec + lbl_w)    # extends to cover the label

        extents_sec.append((x0_s, x1_s))

        # Find a free row
        row = 0
        while any(not (x1_s <= sx0 or x0_s >= sx1)
                  for sx0, sx1 in row_slots.get(row, [])):
            row += 1
        row_slots.setdefault(row, []).append((x0_s, x1_s))
        assigned_rows.append(row)

    # Draw arrows + labels
    for td, row, (x0_s, x1_s) in zip(task_data, assigned_rows, extents_sec):
        task    = td['task']
        color   = td['color']
        arrow_y = base_y - row * row_step
        label_y = arrow_y + row_step * 0.30

        # ── Bidirectional arrow as a shape line + two arrowheads ─────────────
        # Plotly doesn't support <-> arrowstyle natively, so we draw:
        #   • a dotted line from start to end at arrow_y
        #   • left arrowhead annotation at start
        #   • right arrowhead annotation at end
        #   • label annotation slightly above arrow_y

        # Dotted line (drawn as a zero-height filled shape)
        fig.add_shape(
            type='line',
            x0=task.start_time, x1=task.end_time,
            y0=arrow_y, y1=arrow_y,
            line=dict(color=color, width=1.2, dash='dot'),
            layer='above',
        )

        # Left arrowhead  ◄
        fig.add_annotation(
            x=task.start_time, y=arrow_y,
            ax=task.end_time,  ay=arrow_y,
            xref='x', yref='y', axref='x', ayref='y',
            showarrow=True,
            arrowhead=2, arrowsize=0.8, arrowwidth=1.2,
            arrowcolor=color,
            text='',
        )

        # Right arrowhead  ►
        fig.add_annotation(
            x=task.end_time,   y=arrow_y,
            ax=task.start_time, ay=arrow_y,
            xref='x', yref='y', axref='x', ayref='y',
            showarrow=True,
            arrowhead=2, arrowsize=0.8, arrowwidth=1.2,
            arrowcolor=color,
            text='',
        )

        # Test ID label (with white background box, matching mpl bbox style)
        fig.add_annotation(
            x=task.start_time, y=label_y,
            xref='x', yref='y',
            text=f'<b>{task.display_id}</b>',
            showarrow=False,
            font=dict(size=label_fs, color=color, family='sans-serif'),
            xanchor='left', yanchor='bottom',
            bgcolor='rgba(255,255,255,0.85)',
            bordercolor=color,
            borderwidth=0.8,
            borderpad=2,
        )

    # ── Layout ────────────────────────────────────────────────────────────────
    y_range = None
    if y_min_cfg is not None and y_max_cfg is not None:
        y_range = [float(y_min_cfg), float(y_max_cfg)]
    elif flat_points:
        pad = data_range * 0.05
        y_range = [data_min - pad, data_max + pad]

    x_range = None
    if x_min_dt and x_max_dt:
        x_range = [x_min_dt, x_max_dt]

    fig.update_layout(
        title=dict(text=cc.get('title', 'Data Over Time with Events'),
                   font=dict(size=18), x=0.5),
        xaxis=dict(
            title=ac.get('x_label', 'Date & Time'),
            range=x_range,
            showgrid=True, gridcolor='rgba(80,80,80,0.25)',
            tickformat='%H:%M<br>%b %d',
            showspikes=True, spikemode='across', spikesnap='cursor',
            spikedash='solid', spikecolor='gray', spikethickness=1,
        ),
        yaxis=dict(
            title=ac.get('y_label', 'Value'),
            range=y_range,
            showgrid=True, gridcolor='rgba(80,80,80,0.25)',
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        hovermode='x unified',
        # Legend is rebuilt below as annotations — hide the auto legend
        showlegend=True,
        legend=dict(
            orientation='v',
            x=1.02, xanchor='left',
            y=1.0,  yanchor='top',
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(180,180,180,0.8)',
            borderwidth=1,
            font=dict(size=label_fs),
            title=dict(text=''),
        ),
        margin=dict(l=70, r=320, t=70, b=80),
    )

    # ── Right-side legend table (mirrors matplotlib _create_legend) ───────────
    #
    # We draw it as a paper-referenced annotation block at x=1.02, y=0..1.
    # Format:
    #   [color line]  Series Name
    #   ──────────────────────────
    #   TestID (bold)    Description
    #
    # Because Plotly annotations don't support mixed bold/normal in one block,
    # we use HTML tags with <b> inside the text string.
    #
    wrap_w    = rc.get('legend_wrap_width', 28)
    all_configs = config.get_all_series_configs()

    # Build the annotation text
    lines_html = []

    # Series rows: colored line indicator + name
    for sc in all_configs:
        sname = sc.get('name', 'Series')
        scolor = sc.get('line_color', '#1f77b4')
        # Unicode dash in color acts as swatch
        lines_html.append(
            f'<span style="color:{scolor}">━━</span>  <b>{sname}</b>'
        )

    # Separator
    lines_html.append('<span style="color:#cccccc">──────────────────────</span>')

    # Task rows (deduplicated)
    seen_ids: Dict[str, bool] = {}
    for task in tasks:
        key = task.display_id
        if key in seen_ids:
            continue
        seen_ids[key] = True

        # Get color for this test id
        if gantt_config and gantt_config.is_loaded():
            t_color = gantt_config.get_color_for_test_id(task.test_id)
        else:
            t_color = task_colors.get(task.test_id, '#333333')

        wrapped_desc = _textwrap.wrap(task.description or '', wrap_w) or ['']
        desc_html    = '<br>'.join(wrapped_desc)

        lines_html.append(
            f'<b><span style="color:{t_color}">{task.display_id}</span></b>  {desc_html}'
        )

    legend_text = '<br>'.join(lines_html)

    fig.add_annotation(
        x=1.02, y=1.0,
        xref='paper', yref='paper',
        xanchor='left', yanchor='top',
        text=legend_text,
        showarrow=False,
        align='left',
        font=dict(size=label_fs, family='monospace', color='#1a1a1a'),
        bgcolor='rgba(255,255,255,0.92)',
        bordercolor='rgba(150,150,150,0.7)',
        borderwidth=1,
        borderpad=8,
        width=280,
    )

    return fig


# =============================================================================
# DASH APPLICATION
# =============================================================================

class DashApp:
    """
    Dash-based frontend for Composite Data & Gantt Plotter.

    All backend classes (SeriesDataProcessor, EventDataProcessor,
    CompositeChartGenerator, ConfigManager, GanttConfigManager, PPTBuilder)
    are used exactly as in the original Tkinter version.

    State is held in dcc.Store components (JSON-serialisable dicts) rather
    than tk.StringVar / threading.Event.  Long-running operations
    (generate, batch, PPT build) still run in daemon threads; progress
    is written to a thread-safe list and polled by a dcc.Interval.
    """

    def __init__(self):
        # ── Shared mutable state (thread-safe via list appends) ───────────────
        self._log_lines: List[str] = []
        self._batch_log: List[str] = []
        self._batch_running = False
        self._batch_result: Optional[dict] = None   # set by thread on completion
        self._batch_stop_event = threading.Event()  # set by E-stop button
        self._ppt_log_lines: List[str] = []
        self._ppt_running   = False
        self._ppt_result: Optional[dict] = None     # set by thread on completion

        # Currently loaded objects (rebuilt per generate call, like the original)
        self._config       = ConfigManager(DEFAULT_GANTT_CONFIG_PATH
                                           if os.path.exists(DEFAULT_GANTT_CONFIG_PATH) else None)
        self._gantt_config = GanttConfigManager(
            DEFAULT_GANTT_CONFIG_PATH
            if os.path.exists(DEFAULT_GANTT_CONFIG_PATH) else None)

        self._logger = GUILogger(callback=self._log_lines.append)

        # Last generated data (kept in memory — no temp file)
        self._last_all_data_points: Optional[List[List[DataPoint]]] = None
        self._last_tasks:            Optional[List[Task]]            = None
        self._last_png_bytes:        Optional[bytes]                 = None  # Matplotlib PNG in memory
        self._last_pptx_path:        Optional[str]                   = None

        self._ensure_assets()
        self._start_tk_dispatcher()   # must come before _register_flask_routes
        self._app = self._build_app()
        self._register_callbacks()
        self._register_flask_routes()

    # ──────────────────────────────────────────────────────────────────────────
    # APP LAYOUT
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_assets():
        """Write log color CSS into assets/ so Dash auto-loads it."""
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        css_path = os.path.join(assets_dir, 'log_colors.css')
        css = (
            ".log-info    { color: #a6e3a1; }\n"
            ".log-warning { color: #f9e2af; }\n"
            ".log-error   { color: #f38ba8; }\n"
            ".log-debug   { color: #89b4fa; }\n"
            ".log-default { color: #cdd6f4; }\n"
        )
        if not os.path.exists(css_path):
            with open(css_path, 'w') as f:
                f.write(css)

    # ── reusable file-input row builder ──────────────────────────────────────
    @staticmethod
    def _file_row(label: str, input_id: str, browse_id: str, upload_id: str,
                  placeholder: str, extra_btn=None, width_label=2):
        """
        A labelled file-input row with:
          • text input (typed / paste path)
          • Browse button (opens OS file picker via Flask route)
          • dcc.Upload drop-zone (drag a file → path auto-fills)
          • optional extra button (e.g. Preview / Load)
        """
        drop_style = {
            'border': '1.5px dashed #adb5bd',
            'borderRadius': '6px',
            'padding': '4px 10px',
            'fontSize': '11px',
            'color': '#6c757d',
            'cursor': 'pointer',
            'textAlign': 'center',
            'lineHeight': '28px',
            'minWidth': '110px',
        }
        buttons = [
            dbc.Button("📁 Browse", id=browse_id, color='secondary',
                       size='sm', className='me-1'),
            dcc.Upload(id=upload_id,
                       children=html.Span("⬆ Drop file"),
                       style=drop_style,
                       multiple=False,
                       className='me-1 d-inline-block'),
        ]
        if extra_btn:
            buttons.append(extra_btn)
        return dbc.Row([
            dbc.Col(dbc.Label(label), width=width_label),
            dbc.Col(dbc.Input(id=input_id, placeholder=placeholder, size='sm'), width=True),
            dbc.Col(html.Div(buttons, className='d-flex align-items-center'), width='auto'),
        ], className="mb-2 align-items-center")

    @staticmethod
    def _folder_drop_row(label: str, input_id: str, upload_id: str, placeholder: str):
        """
        Folder path row — no OS picker (browsers can't pick folders).
        Drag any file FROM inside the folder → app extracts the folder path.
        """
        drop_style = {
            'border': '1.5px dashed #adb5bd',
            'borderRadius': '6px',
            'padding': '4px 10px',
            'fontSize': '11px',
            'color': '#6c757d',
            'cursor': 'pointer',
            'textAlign': 'center',
            'lineHeight': '28px',
            'minWidth': '150px',
        }
        return dbc.Row([
            dbc.Col(dbc.Label(label), width=2),
            dbc.Col(dbc.Input(id=input_id, placeholder=placeholder, size='sm'), width=True),
            dbc.Col(
                dcc.Upload(id=upload_id,
                           children=html.Span("⬆ Drop any file from folder"),
                           style=drop_style,
                           multiple=False,
                           className='d-inline-block'),
                width='auto'),
        ], className="mb-2 align-items-center")

    def _build_app(self) -> dash.Dash:
        app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.FLATLY],
            title='Composite Data Plotter',
            suppress_callback_exceptions=True,
        )

        # ── CSS for color-coded log is injected via assets/log_colors.css ──────
        # Dash auto-loads any .css file from the 'assets/' folder next to the script.
        # The file is created at startup if it doesn't exist (see _ensure_assets below).
        custom_css = html.Div(id='_css-placeholder', style={'display': 'none'})

        # ── Navbar ────────────────────────────────────────────────────────────
        header = dbc.Navbar(
            dbc.Container([
                html.Span("📊 Composite Data & Gantt Plotter", className="navbar-brand fw-bold"),
                html.Small(" — Dash Edition", className="text-muted"),
            ], fluid=True),
            color="primary", dark=True, className="mb-3",
        )

        # ── Log panel (shared, collapsible) — hidden at startup ─────────────
        log_panel = dbc.Card(className="mb-3", id='log-card', children=[
            dbc.CardHeader(dbc.Row([
                dbc.Col(html.B("Log"), width="auto"),
                dbc.Col([
                    dbc.Button("Copy", id='btn-copy-log', size='sm', color='info',
                               outline=True, className='me-1'),
                    dbc.Button("Clear", id='btn-clear-log', size='sm',
                               color='secondary', outline=True, className='me-1'),
                    dbc.Button("Show Log", id='btn-toggle-log', size='sm',
                               color='secondary', outline=True),
                ], className='ms-auto d-flex align-items-center', width='auto'),
            ], justify="between", align="center")),
            dbc.Collapse(id='log-collapse', is_open=False, children=[
                dbc.CardBody([
                    # Log content rendered as HTML for color-coding
                    html.Div(id='log-output', style={
                        'height': '260px', 'overflowY': 'auto',
                        'fontSize': '11px', 'background': '#1e1e2e',
                        'borderRadius': '6px', 'padding': '10px',
                        'fontFamily': 'monospace', 'whiteSpace': 'pre-wrap',
                    }),
                    # Hidden textarea for clipboard copy
                    html.Textarea(id='log-text-hidden',
                                  style={'position': 'absolute', 'left': '-9999px',
                                         'top': 0, 'opacity': 0},
                                  readOnly=True),
                ]),
            ]),
        ])

        # ── Tab 1: Chart Plotter ──────────────────────────────────────────────
        chart_tab = dbc.Tab(label="📊 Chart Plotter", tab_id="tab-chart", children=[
            dbc.Container(fluid=True, children=[

                # Gantt / Event overlay card
                dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("Gantt / Event Overlay")),
                    dbc.CardBody([
                        self._file_row(
                            "Gantt Config (.json):", 'gantt-config-path',
                            'btn-browse-gantt', 'upload-gantt',
                            'e.g. config_gantt.json',
                        ),
                        html.Div(id='gantt-config-status', className="text-muted small mb-2"),
                        html.Hr(className="my-2"),
                        self._file_row(
                            "Event / Task CSV:", 'event-file-path',
                            'btn-browse-event', 'upload-event',
                            'Path to event CSV…',
                            extra_btn=dbc.Button("Preview", id='btn-preview-events',
                                                 color='info', size='sm', outline=True),
                        ),
                    ]),
                ]),

                # Single chart card
                dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("Single Chart")),
                    dbc.CardBody([
                        self._file_row(
                            "Plot Config (.json):", 'plot-config-path',
                            'btn-browse-config', 'upload-config',
                            'Path to plot config JSON…',
                        ),
                        html.Div(id='plot-config-status', className="text-muted small mb-2"),
                        html.Hr(className="my-2"),
                        self._file_row(
                            "Series Data File:", 'series-file-path',
                            'btn-browse-series', 'upload-series',
                            'Path to CSV / TXT data…',
                            extra_btn=dbc.Button("Preview", id='btn-preview-series',
                                                 color='info', size='sm', outline=True),
                        ),
                        # Export output path row
                        dbc.Row([
                            dbc.Col(dbc.Label("Export Output:"), width=2),
                            dbc.Col(dbc.Input(id='export-output-path',
                                             placeholder='Full path for saved PNG/PDF/SVG…',
                                             size='sm'), width=True),
                            dbc.Col(dbc.Button("📁 Browse", id='btn-browse-export',
                                               color='secondary', size='sm'), width='auto'),
                        ], className="mb-2 align-items-center"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button("▶ Generate Chart", id='btn-generate',
                                           color='primary', className='me-2'),
                                dbc.Button("💾 Export Chart", id='btn-export',
                                           color='success', className='me-2', disabled=True),
                                dbc.Button("⚙ Settings", id='btn-settings',
                                           color='secondary', outline=True),
                            ], className="mt-2"),
                        ]),
                        html.Div(id='generate-status', className="mt-2 small"),
                    ]),
                ]),

                # Batch processing card
                dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("Batch Processing")),
                    dbc.CardBody([
                        self._folder_drop_row("Config Folder:", 'batch-config-folder',
                                              'upload-batch-config',
                                              'Folder of plot config JSONs…'),
                        self._folder_drop_row("Data Folder:", 'batch-data-folder',
                                              'upload-batch-data',
                                              'Folder of CSV / TXT data files…'),
                        self._folder_drop_row("Output Folder:", 'batch-output-folder',
                                              'upload-batch-output',
                                              'Output folder for exported PNGs…'),
                        html.Div(id='batch-summary', className="text-primary small mb-2"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Button("▶ Run Batch", id='btn-batch', color='warning',
                                           className='me-2'),
                                dbc.Button("⏹ E-Stop", id='btn-estop', color='danger',
                                           disabled=True,
                                           title='Stop batch after current charts finish'),
                            ], className='d-flex align-items-center'),
                        ]),
                        html.Div(id='batch-status', className="mt-2 small"),
                    ]),
                ]),

                # ── Batch Progress Log ────────────────────────────────────────
                dbc.Card(className="mb-3", id='batch-log-card', children=[
                    dbc.CardHeader(dbc.Row([
                        dbc.Col(html.B("Batch Progress Log"), width="auto"),
                        dbc.Col([
                            dbc.Button("Copy", id='btn-copy-batch-log', size='sm',
                                       color='info', outline=True, className='me-1'),
                            dbc.Button("Clear", id='btn-clear-batch-log', size='sm',
                                       color='secondary', outline=True, className='me-1'),
                            dbc.Button("Show Log", id='btn-toggle-batch-log', size='sm',
                                       color='secondary', outline=True),
                        ], className='ms-auto d-flex align-items-center', width='auto'),
                    ], justify="between", align="center")),
                    dbc.Collapse(id='batch-log-collapse', is_open=False, children=[
                        dbc.CardBody([
                            html.Div(id='batch-log-output', style={
                                'height': '220px', 'overflowY': 'auto',
                                'fontSize': '11px', 'background': '#1e2030',
                                'color': '#c3e88d', 'borderRadius': '6px',
                                'padding': '10px', 'fontFamily': 'monospace',
                                'whiteSpace': 'pre-wrap',
                            }),
                            html.Textarea(id='batch-log-text-hidden',
                                          style={'position': 'absolute', 'left': '-9999px',
                                                 'top': 0, 'opacity': 0},
                                          readOnly=True),
                        ]),
                    ]),
                ]),

                log_panel,
            ]),
        ])

        # ── Tab 2: Live Preview ───────────────────────────────────────────────
        preview_tab = dbc.Tab(label="🔍 Live Preview", tab_id="tab-preview", children=[
            dbc.Container(fluid=True, children=[

                # Plotly interactive chart
                dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("Interactive Chart Preview")),
                    dbc.CardBody(
                        dcc.Graph(id='plotly-preview',
                                  style={'height': '500px'},
                                  config={'displayModeBar': True,
                                          'scrollZoom': True,
                                          'toImageButtonOptions': {
                                              'format': 'png', 'filename': 'composite_preview',
                                              'height': 900, 'width': 1600, 'scale': 2}}),
                    ),
                ]),

                dbc.Row([
                    # Data summary
                    dbc.Col(dbc.Card(className="mb-3", children=[
                        dbc.CardHeader(html.B("Data Summary")),
                        dbc.CardBody(html.Div(id='data-summary-table')),
                    ]), width=5),

                    # Event table
                    dbc.Col(dbc.Card(className="mb-3", children=[
                        dbc.CardHeader(html.B("Event / Task Table")),
                        dbc.CardBody(html.Div(id='event-summary-table',
                                              style={'maxHeight': '280px', 'overflowY': 'auto'})),
                    ]), width=7),
                ]),
            ]),
        ])

        # ── Tab 3: PPT Builder ────────────────────────────────────────────────
        ppt_tab = dbc.Tab(label="📑 PPT Builder", tab_id="tab-ppt", children=[
            dbc.Container(fluid=True, children=[
                dbc.Alert(
                    "python-pptx not installed. Run: pip install python-pptx",
                    color="danger", is_open=not _PPTX_AVAILABLE, className="mb-3",
                ),
                dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("PowerPoint Builder")),
                    dbc.CardBody([
                        # Image folder — drag any file from it to extract folder path
                        self._folder_drop_row("Image Folder:", 'ppt-img-folder',
                                              'upload-ppt-img',
                                              'Folder containing PNG/JPG images…'),
                        # PPTX template — browse button
                        self._file_row(
                            "PPTX Template:", 'ppt-template',
                            'btn-browse-ppt-tmpl', 'upload-ppt-tmpl-file',
                            'Path to .pptx template…',
                        ),
                        # Output folder — drag any file from it
                        self._folder_drop_row("Output Folder:", 'ppt-output-folder',
                                              'upload-ppt-out-folder',
                                              'Output folder for .pptx…'),
                        dbc.Row([
                            dbc.Col(dbc.Label("Output Filename:"), width=3),
                            dbc.Col(dbc.Input(id='ppt-filename', value='output.pptx',
                                             size='sm'), width=5),
                            dbc.Col(dbc.Label("DPI:"), width=1),
                            dbc.Col(dbc.Input(id='ppt-dpi', value='96', type='number',
                                             min=72, max=600, size='sm'), width=3),
                        ], className="mb-2 align-items-center"),
                        dbc.Row([
                            dbc.Col([
                                dbc.Checklist(
                                    id='ppt-auto-resize',
                                    options=[{'label': ' Auto-resize slide canvas to image dimensions',
                                              'value': 'yes'}],
                                    value=['yes'],
                                    className="mb-2",
                                ),
                            ]),
                        ]),
                        dbc.Button("📑 Build PPTX", id='btn-ppt-build', color='primary',
                                   disabled=not _PPTX_AVAILABLE),
                        html.Div(id='ppt-build-status', className="mt-2 small"),
                    ]),
                ]),
                dbc.Card(children=[
                    dbc.CardHeader(dbc.Row([
                        dbc.Col(html.B("PPT Builder Log"), width="auto"),
                        dbc.Col([
                            dbc.Button("Copy", id='btn-copy-ppt-log', size='sm',
                                       color='info', outline=True, className='me-1'),
                            dbc.Button("Clear", id='btn-clear-ppt-log', size='sm',
                                       color='secondary', outline=True, className='me-1'),
                            dbc.Button("Show Log", id='btn-toggle-ppt-log', size='sm',
                                       color='secondary', outline=True),
                        ], className='ms-auto d-flex align-items-center', width='auto'),
                    ], justify="between", align="center")),
                    dbc.Collapse(id='ppt-log-collapse', is_open=False, children=[
                        dbc.CardBody([
                            html.Div(id='ppt-log-output', style={
                                'height': '300px', 'overflowY': 'auto',
                                'fontSize': '11px', 'background': '#1e1e2e',
                                'color': '#cdd6f4', 'borderRadius': '6px',
                                'padding': '10px', 'fontFamily': 'monospace',
                                'whiteSpace': 'pre-wrap',
                            }),
                            html.Textarea(id='ppt-log-text-hidden',
                                          style={'position': 'absolute', 'left': '-9999px',
                                                 'top': 0, 'opacity': 0},
                                          readOnly=True),
                        ]),
                    ]),
                ]),
            ]),
        ])

        # ── Settings modal ────────────────────────────────────────────────────
        settings_modal = dbc.Modal(id='settings-modal', size='lg', is_open=False, children=[
            dbc.ModalHeader(dbc.ModalTitle("Chart Settings & Layout")),
            dbc.ModalBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Resolution Preset"),
                        dbc.Select(id='preset-select',
                                   options=[{'label': k, 'value': k}
                                            for k in RESOLUTION_PRESETS],
                                   value="2560×1440 (2K/QHD)  ← default"),
                    ], width=12, className="mb-3"),
                ]),
                dbc.Row([
                    dbc.Col([dbc.Label("Width (px)"),
                             dbc.Input(id='settings-width', value='2560', type='number',
                                       min=320, max=7680)], width=3),
                    dbc.Col([dbc.Label("Height (px)"),
                             dbc.Input(id='settings-height', value='1440', type='number',
                                       min=240, max=4320)], width=3),
                    dbc.Col([dbc.Label("DPI"),
                             dbc.Input(id='settings-dpi', value='96', type='number',
                                       min=72, max=1200)], width=3),
                    dbc.Col([dbc.Label("Font Scale"),
                             dbc.Input(id='settings-font-scale', value='1.0',
                                       type='number', min=0.5, max=3.0, step=0.1)], width=3),
                ], className="mb-3"),
                dbc.Row([
                    dbc.Col([dbc.Label("Linewidth Scale"),
                             dbc.Input(id='settings-lw-scale', value='1.0',
                                       type='number', min=0.5, max=3.0, step=0.1)], width=3),
                    dbc.Col([dbc.Label("Legend Width (px)"),
                             dbc.Input(id='settings-lgw', value='500', type='number',
                                       min=100, max=2000, step=10)], width=3),
                    dbc.Col([dbc.Label("Subplot Left"),
                             dbc.Input(id='settings-left', value='0.03',
                                       type='number', min=0.0, max=0.5, step=0.01)], width=3),
                    dbc.Col([dbc.Label("Subplot Bottom"),
                             dbc.Input(id='settings-bottom', value='0.06',
                                       type='number', min=0.0, max=0.5, step=0.01)], width=3),
                ], className="mb-3"),
                html.Hr(className="my-2"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Parallel Workers (Batch)"),
                        dbc.Input(id='batch-workers', value='4', type='number',
                                  min=1, max=16),
                        html.Small("Number of charts rendered simultaneously during batch runs.",
                                   className="text-muted"),
                    ], width=4),
                ], className="mb-3"),
                html.Div(id='settings-info', className="text-muted small"),
            ]),
            dbc.ModalFooter([
                dbc.Button("Apply", id='btn-settings-apply', color='primary', className='me-2'),
                dbc.Button("Cancel", id='btn-settings-cancel', color='secondary'),
            ]),
        ])

        # ── Hidden preview / data-sharing modal ──────────────────────────────
        data_modal = dbc.Modal(id='data-preview-modal', size='xl', is_open=False, children=[
            dbc.ModalHeader(dbc.ModalTitle(id='data-preview-title', children="Preview")),
            dbc.ModalBody(html.Div(id='data-preview-content',
                                   style={'overflowX': 'auto', 'maxHeight': '70vh',
                                          'overflowY': 'auto'})),
            dbc.ModalFooter(dbc.Button("Close", id='btn-close-preview', color='secondary')),
        ])

        # ── Stores & polling interval ─────────────────────────────────────────
        stores = html.Div([
            dcc.Store(id='store-config-loaded',       data=False),
            dcc.Store(id='store-gantt-loaded',        data=False),
            dcc.Store(id='store-preview-ready',       data=False),
            dcc.Store(id='store-series-summary',      data=None),
            dcc.Store(id='store-task-summary',        data=None),
            dcc.Store(id='store-batch-result',        data=None),
            dcc.Store(id='store-ppt-result',          data=None),
            dcc.Interval(id='interval-log',    interval=800,  n_intervals=0),
            dcc.Interval(id='interval-batch',  interval=1000, n_intervals=0),
            dcc.Interval(id='interval-ppt',    interval=1000, n_intervals=0),
            dcc.Download(id='download-chart'),
        ])

        app.layout = html.Div([
            custom_css,
            header,
            dbc.Tabs(id='main-tabs', active_tab='tab-chart', children=[
                chart_tab, preview_tab, ppt_tab,
            ], className="mb-3 px-3"),
            settings_modal,
            data_modal,
            stores,
        ])

        # ── Clientside: auto-scroll log to bottom on update ───────────────────
        app.clientside_callback(
            """
            function(children) {
                var el = document.getElementById('log-output');
                if (el) { el.scrollTop = el.scrollHeight; }
                return window.dash_clientside.no_update;
            }
            """,
            Output('log-output', 'data-scroll'),
            Input('log-output', 'children'),
        )

        # ── Clientside: auto-scroll batch log ─────────────────────────────────
        app.clientside_callback(
            """
            function(children) {
                var el = document.getElementById('batch-log-output');
                if (el) { el.scrollTop = el.scrollHeight; }
                return window.dash_clientside.no_update;
            }
            """,
            Output('batch-log-output', 'data-scroll'),
            Input('batch-log-output', 'children'),
        )

        # ── Clientside: auto-scroll PPT log ───────────────────────────────────
        app.clientside_callback(
            """
            function(children) {
                var el = document.getElementById('ppt-log-output');
                if (el) { el.scrollTop = el.scrollHeight; }
                return window.dash_clientside.no_update;
            }
            """,
            Output('ppt-log-output', 'data-scroll'),
            Input('ppt-log-output', 'children'),
        )

        # ── Clientside: copy main log ─────────────────────────────────────────
        app.clientside_callback(
            """
            function(n_clicks) {
                if (!n_clicks) return '';
                var el = document.getElementById('log-output');
                if (!el) return '';
                var text = el.innerText || el.textContent || '';
                navigator.clipboard.writeText(text).catch(function(){
                    var ta = document.getElementById('log-text-hidden');
                    if (ta) { ta.value = text; ta.select(); document.execCommand('copy'); }
                });
                return '';
            }
            """,
            Output('log-text-hidden', 'value'),
            Input('btn-copy-log', 'n_clicks'),
            prevent_initial_call=True,
        )

        # ── Clientside: copy batch log ────────────────────────────────────────
        app.clientside_callback(
            """
            function(n_clicks) {
                if (!n_clicks) return '';
                var el = document.getElementById('batch-log-output');
                if (!el) return '';
                var text = el.innerText || el.textContent || '';
                navigator.clipboard.writeText(text).catch(function(){
                    var ta = document.getElementById('batch-log-text-hidden');
                    if (ta) { ta.value = text; ta.select(); document.execCommand('copy'); }
                });
                return '';
            }
            """,
            Output('batch-log-text-hidden', 'value'),
            Input('btn-copy-batch-log', 'n_clicks'),
            prevent_initial_call=True,
        )

        # ── Clientside: copy PPT log ──────────────────────────────────────────
        app.clientside_callback(
            """
            function(n_clicks) {
                if (!n_clicks) return '';
                var el = document.getElementById('ppt-log-output');
                if (!el) return '';
                var text = el.innerText || el.textContent || '';
                navigator.clipboard.writeText(text).catch(function(){
                    var ta = document.getElementById('ppt-log-text-hidden');
                    if (ta) { ta.value = text; ta.select(); document.execCommand('copy'); }
                });
                return '';
            }
            """,
            Output('ppt-log-text-hidden', 'value'),
            Input('btn-copy-ppt-log', 'n_clicks'),
            prevent_initial_call=True,
        )

        return app

    # ──────────────────────────────────────────────────────────────────────────
    # FLASK ROUTES (server-side file/folder pickers via tkinter.filedialog)
    # ──────────────────────────────────────────────────────────────────────────

    # ──────────────────────────────────────────────────────────────────────────
    # TKINTER DIALOG DISPATCHER
    # ──────────────────────────────────────────────────────────────────────────
    # Tkinter's Tcl/Tk runtime is not thread-safe: file dialogs MUST be called
    # from the single thread that owns the Tk root.  Flask routes run on worker
    # threads, so we cannot call filedialog directly from them.
    #
    # Solution: one persistent "Tk dispatcher" daemon thread owns the Tk root
    # for its entire lifetime.  Flask routes post a job dict onto a Queue and
    # block on a threading.Event; the dispatcher thread executes the dialog,
    # puts the result back, and sets the Event.  The Flask route then returns.
    # ──────────────────────────────────────────────────────────────────────────

    def _start_tk_dispatcher(self):
        """
        Start the single persistent Tkinter dispatcher thread.
        Must be called once before any Flask route is hit.
        """
        import queue as _queue
        self._tk_queue: _queue.Queue = _queue.Queue()

        def _dispatcher():
            try:
                import tkinter as tk
                from tkinter import filedialog
            except ImportError:
                # tkinter not available (headless / non-Windows env)
                # Flask routes will return empty path; Browse buttons disabled gracefully
                while True:
                    try:
                        job = self._tk_queue.get(timeout=1)
                        if job is None:
                            break
                        job['result'].append('')
                        job['done'].set()
                    except Exception:
                        pass
                return

            # One root that lives for the whole process lifetime
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)

            while True:
                try:
                    job = self._tk_queue.get(timeout=0.2)
                except _queue.Empty:
                    # Keep the Tk event loop ticking so the window stays responsive
                    root.update_idletasks()
                    continue

                if job is None:          # sentinel → shut down
                    break

                mode       = job['mode']
                title      = job['title']
                filetypes  = job.get('filetypes') or [('All', '*.*')]
                save       = job.get('save', False)
                default_ext= job.get('default_ext', '')
                result_box = job['result']   # list([]) – filled by us
                done_event = job['done']     # threading.Event

                try:
                    root.deiconify()         # bring to front
                    root.lift()
                    root.focus_force()
                    root.update()

                    if mode == 'file' and save:
                        path = filedialog.asksaveasfilename(
                            parent=root, title=title,
                            defaultextension=default_ext,
                            filetypes=filetypes)
                    elif mode == 'file':
                        path = filedialog.askopenfilename(
                            parent=root, title=title,
                            filetypes=filetypes)
                    else:   # folder
                        path = filedialog.askdirectory(
                            parent=root, title=title)

                    result_box.append(path or '')
                except Exception:
                    result_box.append('')
                finally:
                    root.withdraw()
                    done_event.set()

        t = threading.Thread(target=_dispatcher, name='TkDialogDispatcher',
                             daemon=True)
        t.start()
        self._tk_dispatcher_thread = t

    def _tk_pick(self, mode: str, title: str, filetypes=None,
                 save: bool = False, default_ext: str = '') -> str:
        """
        Submit a dialog request to the dispatcher thread and block until done.
        Safe to call from any Flask worker thread.
        """
        result_box = []
        done_event = threading.Event()
        self._tk_queue.put({
            'mode':        mode,
            'title':       title,
            'filetypes':   filetypes,
            'save':        save,
            'default_ext': default_ext,
            'result':      result_box,
            'done':        done_event,
        })
        done_event.wait(timeout=120)
        return result_box[0] if result_box else ''

    def _register_flask_routes(self):
        """Register Flask endpoints that open native OS file/folder dialogs."""
        server = self._app.server

        EXT_MAP = {
            'json':   [('JSON', '*.json'), ('All', '*.*')],
            'csv':    [('CSV/TXT', '*.csv *.txt'), ('CSV', '*.csv'),
                       ('TXT', '*.txt'), ('All', '*.*')],
            'data':   [('Tab/CSV', '*.txt *.csv'), ('All', '*.*')],
            'png':    [('Image', '*.png *.jpg'), ('All', '*.*')],
            'pptx':   [('PowerPoint', '*.pptx'), ('All', '*.*')],
            'export': [('PNG', '*.png'), ('PDF', '*.pdf'),
                       ('SVG', '*.svg'), ('All', '*.*')],
        }
        TITLE_MAP = {
            'json':   'Select JSON Config File',
            'csv':    'Select Event / Task CSV',
            'data':   'Select Series Data File',
            'png':    'Select Image Folder File',
            'pptx':   'Select PowerPoint Template',
            'export': 'Save Chart As…',
        }
        DEFAULT_EXT_MAP = {'export': '.png', 'pptx': '.pptx'}

        @server.route('/api/pick-file')
        def pick_file():
            from flask import jsonify
            kind = flask_request.args.get('kind', 'json')
            save = flask_request.args.get('save', 'false').lower() == 'true'
            path = self._tk_pick(
                mode='file',
                title=TITLE_MAP.get(kind, 'Select File'),
                filetypes=EXT_MAP.get(kind, [('All', '*.*')]),
                save=save,
                default_ext=DEFAULT_EXT_MAP.get(kind, ''),
            )
            return jsonify({'path': path})

        @server.route('/api/pick-folder')
        def pick_folder():
            from flask import jsonify
            title = flask_request.args.get('title', 'Select Folder')
            path  = self._tk_pick(mode='folder', title=title)
            return jsonify({'path': path})

    # ──────────────────────────────────────────────────────────────────────────
    # CALLBACKS
    # ──────────────────────────────────────────────────────────────────────────

    def _register_callbacks(self):
        app = self._app

        # ── Clientside: Browse buttons call Flask pick endpoints ──────────────
        # One JS callback handles all Browse buttons by reading data-kind attribute.
        # Each Browse button fires fetch('/api/pick-file?kind=X') and puts the
        # returned path into the corresponding Input component.
        _browse_map = [
            # (button_id,            input_id,              kind,     save)
            ('btn-browse-gantt',   'gantt-config-path',   'json',   False),
            ('btn-browse-event',   'event-file-path',     'csv',    False),
            ('btn-browse-config',  'plot-config-path',    'json',   False),
            ('btn-browse-series',  'series-file-path',    'data',   False),
            ('btn-browse-export',  'export-output-path',  'export', True),
            ('btn-browse-ppt-img', 'ppt-img-folder-file', 'png',    False),
            ('btn-browse-ppt-tmpl','ppt-template',        'pptx',   False),
            ('btn-browse-ppt-out', 'ppt-out-file',        'export', True),
        ]
        for btn_id, inp_id, kind, save in _browse_map:
            save_str = 'true' if save else 'false'
            app.clientside_callback(
                f"""
                function(n) {{
                    if (!n) return window.dash_clientside.no_update;
                    return fetch('/api/pick-file?kind={kind}&save={save_str}')
                        .then(r => r.json())
                        .then(d => d.path || window.dash_clientside.no_update);
                }}
                """,
                Output(inp_id, 'value', allow_duplicate=True),
                Input(btn_id, 'n_clicks'),
                prevent_initial_call=True,
            )

        # Folder Browse buttons (batch + PPT)
        _folder_browse_map = [
            ('btn-browse-folder-batch-config-folder', 'batch-config-folder', 'Select Config Folder'),
            ('btn-browse-folder-batch-data-folder',   'batch-data-folder',   'Select Data Folder'),
            ('btn-browse-folder-batch-output-folder', 'batch-output-folder', 'Select Output Folder'),
            ('btn-browse-folder-ppt-img-folder',      'ppt-img-folder',      'Select Image Folder'),
            ('btn-browse-folder-ppt-output-folder',   'ppt-output-folder',   'Select Output Folder'),
        ]
        for btn_id, inp_id, title in _folder_browse_map:
            app.clientside_callback(
                f"""
                function(n) {{
                    if (!n) return window.dash_clientside.no_update;
                    return fetch('/api/pick-folder?title={title}')
                        .then(r => r.json())
                        .then(d => d.path || window.dash_clientside.no_update);
                }}
                """,
                Output(inp_id, 'value', allow_duplicate=True),
                Input(btn_id, 'n_clicks'),
                prevent_initial_call=True,
            )

        # ── dcc.Upload → save to temp dir, fill path (single files) ──────────
        # Files are uploaded to a temp directory (never permanently saved) so
        # the rest of the app can load them by file path as normal.
        _upload_inputs = [
            ('upload-gantt',   'gantt-config-path'),
            ('upload-event',   'event-file-path'),
            ('upload-config',  'plot-config-path'),
            ('upload-series',  'series-file-path'),
        ]
        for upload_id, inp_id in _upload_inputs:
            @app.callback(
                Output(inp_id, 'value', allow_duplicate=True),
                Input(upload_id, 'contents'),
                State(upload_id, 'filename'),
                prevent_initial_call=True,
            )
            def _save_uploaded_file(contents, filename, _uid=upload_id, _iid=inp_id):
                """Save uploaded file to temp dir and return its path."""
                if not contents or not filename:
                    raise PreventUpdate
                # Decode base64 content (format: "data:<mime>;base64,<data>")
                try:
                    content_type, content_string = contents.split(',', 1)
                    decoded = base64.b64decode(content_string)
                    out_path = os.path.join(self._temp_dir, filename)
                    with open(out_path, 'wb') as f:
                        f.write(decoded)
                    return out_path
                except Exception:
                    raise PreventUpdate

        # ── dcc.Upload → extract FOLDER path (batch folder drops) ────────────
        _folder_drops = [
            ('upload-batch-config', 'batch-config-folder'),
            ('upload-batch-data',   'batch-data-folder'),
            ('upload-batch-output', 'batch-output-folder'),
        ]
        for upload_id, inp_id in _folder_drops:
            @app.callback(
                Output(inp_id, 'value', allow_duplicate=True),
                Input(upload_id, 'filename'),
                State(inp_id, 'value'),
                prevent_initial_call=True,
            )
            def _fill_folder_from_drop(filename, current, _uid=upload_id, _iid=inp_id):
                if not filename:
                    raise PreventUpdate
                # Try to locate the file to extract its parent folder
                for base in ([os.path.dirname(current)] if current else []) + [os.getcwd()]:
                    candidate = os.path.join(base, filename)
                    if os.path.isfile(candidate):
                        return os.path.dirname(os.path.abspath(candidate))
                # If we can't find the file, return current unchanged
                raise PreventUpdate

        # ── PPT-specific folder drops (image folder, output folder) ───────────
        _ppt_folder_drops = [
            ('upload-ppt-img',        'ppt-img-folder'),
            ('upload-ppt-out-folder', 'ppt-output-folder'),
        ]
        for upload_id, inp_id in _ppt_folder_drops:
            @app.callback(
                Output(inp_id, 'value', allow_duplicate=True),
                Input(upload_id, 'filename'),
                State(inp_id, 'value'),
                prevent_initial_call=True,
            )
            def _fill_ppt_folder(filename, current, _uid=upload_id, _iid=inp_id):
                if not filename:
                    raise PreventUpdate
                for base in ([os.path.dirname(current)] if current else []) + [os.getcwd()]:
                    candidate = os.path.join(base, filename)
                    if os.path.isfile(candidate):
                        return os.path.dirname(os.path.abspath(candidate))
                raise PreventUpdate

        # ── PPT template upload (single file) ────────────────────────────────
        @app.callback(
            Output('ppt-template', 'value', allow_duplicate=True),
            Input('upload-ppt-tmpl-file', 'filename'),
            State('ppt-template', 'value'),
            prevent_initial_call=True,
        )
        def fill_ppt_template(filename, current):
            if not filename:
                raise PreventUpdate
            for base in ([os.path.dirname(current)] if current else []) + [os.getcwd()]:
                candidate = os.path.join(base, filename)
                if os.path.isfile(candidate):
                    return candidate
            return filename

        # ── Log toggle (main) ─────────────────────────────────────────────────
        @app.callback(
            Output('log-collapse', 'is_open'),
            Output('btn-toggle-log', 'children'),
            Input('btn-toggle-log', 'n_clicks'),
            State('log-collapse', 'is_open'),
            prevent_initial_call=True,
        )
        def toggle_log(_, is_open):
            new_open = not is_open
            return new_open, "Hide Log" if new_open else "Show Log"

        # ── Batch log toggle ──────────────────────────────────────────────────
        @app.callback(
            Output('batch-log-collapse', 'is_open'),
            Output('btn-toggle-batch-log', 'children'),
            Input('btn-toggle-batch-log', 'n_clicks'),
            State('batch-log-collapse', 'is_open'),
            prevent_initial_call=True,
        )
        def toggle_batch_log(_, is_open):
            new_open = not is_open
            return new_open, "Hide Log" if new_open else "Show Log"

        # ── PPT log toggle ────────────────────────────────────────────────────
        @app.callback(
            Output('ppt-log-collapse', 'is_open'),
            Output('btn-toggle-ppt-log', 'children'),
            Input('btn-toggle-ppt-log', 'n_clicks'),
            State('ppt-log-collapse', 'is_open'),
            prevent_initial_call=True,
        )
        def toggle_ppt_log(_, is_open):
            new_open = not is_open
            return new_open, "Hide Log" if new_open else "Show Log"

        # ── Batch log clear ───────────────────────────────────────────────────
        @app.callback(
            Output('batch-log-output', 'children', allow_duplicate=True),
            Input('btn-clear-batch-log', 'n_clicks'),
            prevent_initial_call=True,
        )
        def clear_batch_log(_):
            self._batch_log.clear()
            return []

        # ── PPT log clear ─────────────────────────────────────────────────────
        @app.callback(
            Output('ppt-log-output', 'children', allow_duplicate=True),
            Input('btn-clear-ppt-log', 'n_clicks'),
            prevent_initial_call=True,
        )
        def clear_ppt_log(_):
            self._ppt_log_lines.clear()
            return []

        # ── E-stop batch ──────────────────────────────────────────────────────
        # Sets the stop event; btn-estop visual state is managed by poll_batch_log
        @app.callback(
            Output('store-batch-result', 'data', allow_duplicate=True),
            Input('btn-estop', 'n_clicks'),
            prevent_initial_call=True,
        )
        def estop_batch(_):
            if self._batch_running:
                self._batch_stop_event.set()
                self._logger.warning("E-Stop requested — waiting for in-progress charts to finish…")
            return no_update

        # ── Auto-load Gantt config when path changes ──────────────────────────
        @app.callback(
            Output('gantt-config-status', 'children'),
            Output('store-gantt-loaded', 'data'),
            Input('gantt-config-path', 'value'),
            prevent_initial_call=True,
        )
        def load_gantt(path):
            if not path or not path.strip():
                return "", False
            if not os.path.isfile(path):
                return dbc.Alert(f"File not found: {path}", color="danger", className="py-1"), False
            if self._gantt_config.reload(path):
                gc = self._gantt_config.get_gantt_config()
                self._logger.info(f"Gantt config loaded: {path}")
                return dbc.Alert(f"✓ Loaded: {os.path.basename(path)}  "
                                 f"(bar_alpha={gc.get('bar_alpha','?')})",
                                 color="success", className="py-1"), True
            return dbc.Alert("Failed to load gantt config — check JSON structure.",
                             color="danger", className="py-1"), False

        # ── Auto-load Plot config when path changes ───────────────────────────
        @app.callback(
            Output('plot-config-status', 'children'),
            Output('store-config-loaded', 'data'),
            Input('plot-config-path', 'value'),
            prevent_initial_call=True,
        )
        def load_config(path):
            if not path or not path.strip():
                return "", False
            if not os.path.isfile(path):
                return dbc.Alert(f"File not found: {path}", color="danger", className="py-1"), False
            if self._config.reload(path):
                sname = self._config.get_series_name()
                self._logger.info(f"Config loaded: {path}  |  Series: {sname}")
                return dbc.Alert(f"✓ {os.path.basename(path)}  — Series: {sname}",
                                 color="success", className="py-1"), True
            return dbc.Alert("Failed to load config — check JSON structure.",
                             color="danger", className="py-1"), False

        # ── Preview buttons → open data-preview modal ─────────────────────────
        @app.callback(
            Output('data-preview-modal', 'is_open'),
            Output('data-preview-title', 'children'),
            Output('data-preview-content', 'children'),
            Input('btn-preview-series', 'n_clicks'),
            Input('btn-preview-events', 'n_clicks'),
            Input('btn-close-preview', 'n_clicks'),
            State('series-file-path', 'value'),
            State('event-file-path', 'value'),
            prevent_initial_call=True,
        )
        def handle_previews(n_series, n_events, n_close, series_path, event_path):
            trigger = ctx.triggered_id
            if trigger == 'btn-close-preview':
                return False, "", ""
            if trigger == 'btn-preview-series':
                path, title = series_path, "Series Data Preview"
            else:
                path, title = event_path, "Event / Task Preview"
            if not path or not os.path.isfile(path):
                return True, title, dbc.Alert(f"File not found: {path}", color="danger")
            try:
                df = None
                for sep in (',', '\t', ';', ' '):
                    try:
                        df = pd.read_csv(path, sep=sep)
                        if len(df.columns) > 1:
                            break
                    except Exception:
                        continue
                if df is None or len(df.columns) <= 1:
                    df = pd.read_csv(path)
                preview = df.head(200)
                tbl = dash_table.DataTable(
                    data=preview.astype(str).to_dict('records'),
                    columns=[{'name': c, 'id': c} for c in preview.columns],
                    style_table={'overflowX': 'auto'},
                    style_cell={'fontSize': '11px', 'padding': '4px 8px',
                                'fontFamily': 'monospace'},
                    style_header={'fontWeight': 'bold', 'background': '#f0f0f0'},
                    page_size=50,
                )
                return True, f"{title} ({len(df)} rows, {len(df.columns)} cols)", tbl
            except Exception as e:
                return True, title, dbc.Alert(f"Error: {e}", color="danger")

        # ── Generate chart (single) — no temp file, chart stays in memory ─────
        @app.callback(
            Output('generate-status', 'children'),
            Output('btn-export', 'disabled'),
            Output('store-preview-ready', 'data'),
            Output('store-series-summary', 'data'),
            Output('store-task-summary', 'data'),
            Input('btn-generate', 'n_clicks'),
            State('series-file-path', 'value'),
            State('event-file-path', 'value'),
            prevent_initial_call=True,
        )
        def generate_chart(_, series_path, event_path):
            if not series_path or not os.path.isfile(series_path):
                return dbc.Alert("Series data file not found.", color="warning"), True, False, None, None
            if not event_path or not os.path.isfile(event_path):
                return dbc.Alert("Event CSV file not found.", color="warning"), True, False, None, None
            if not self._config.config:
                return dbc.Alert("Load a plot config file first.", color="warning"), True, False, None, None

            self._logger.info("=" * 50)
            self._logger.info("Starting chart generation…")

            # Load all series data
            all_data_points  = []
            series_summaries = []
            for i, sc in enumerate(self._config.get_all_series_configs()):
                proc = SeriesDataProcessor(
                    logger=self._logger,
                    value_column=sc.get('value_column'),
                    value_column_keywords=sc.get('value_column_keywords', ['value']),
                )
                if not proc.load_data(series_path):
                    msg = f"Failed to load data for series '{sc.get('name', i)}'"
                    self._logger.error(msg)
                    return dbc.Alert(msg, color="danger"), True, False, None, None
                pts = proc.get_data_points()
                all_data_points.append(pts)
                s  = proc.get_summary()
                tr = s['time_range']
                vr = s['value_range']
                series_summaries.append({
                    'Series':    sc.get('name', f'Series {i+1}'),
                    'Points':    s['total_points'],
                    'Start':     str(tr[0]) if tr[0] else '—',
                    'End':       str(tr[1]) if tr[1] else '—',
                    'Value Min': f"{vr[0]:.4f}" if vr[0] is not None else '—',
                    'Value Max': f"{vr[1]:.4f}" if vr[1] is not None else '—',
                })

            # Load events
            event_proc = EventDataProcessor(logger=self._logger)
            if not event_proc.load_csv(event_path):
                return dbc.Alert("Failed to load event CSV.", color="danger"), True, False, None, None
            tasks = event_proc.get_tasks()
            es    = event_proc.get_summary()
            self._logger.info(f"Events: {es['total_tasks']} tasks  IDs: {', '.join(es['test_ids'])}")

            # Generate Matplotlib chart → keep as bytes in memory, NO temp file
            gen = CompositeChartGenerator(self._config, self._logger, self._gantt_config)
            if not gen.generate(all_data_points, tasks):
                return dbc.Alert("Chart generation failed — see log.", color="danger"), True, False, None, None

            buf = io.BytesIO()
            dpi = self._config.get_chart_config().get('dpi', DEFAULT_DPI)
            gen.fig.savefig(buf, format='png', dpi=dpi,
                            bbox_inches=None, facecolor='white', edgecolor='none', pad_inches=0)
            plt.close(gen.fig)
            buf.seek(0)
            self._last_png_bytes       = buf.read()
            self._last_all_data_points = all_data_points
            self._last_tasks           = tasks
            self._logger.info("Chart ready in memory (no temp file written)")

            task_rows = [{'Test ID':     t.display_id,
                          'Description': t.description,
                          'Start':       t.start_time.strftime('%Y-%m-%d %H:%M'),
                          'End':         t.end_time.strftime('%Y-%m-%d %H:%M'),
                          'Norm':        '✓' if t.is_normalization else ''}
                         for t in tasks]

            res     = self._config.get_chart_config().get('resolution_px')
            res_str = f"{int(res[0])}×{int(res[1])} px" if res else ""

            return (
                dbc.Alert(f"✓ Chart ready!  {res_str}  — switch to Live Preview tab.",
                          color="success"),
                False,
                True,
                series_summaries,
                task_rows,
            )

        # ── Export chart — server-side save to user path ──────────────────────
        @app.callback(
            Output('generate-status', 'children', allow_duplicate=True),
            Input('btn-export', 'n_clicks'),
            State('export-output-path', 'value'),
            prevent_initial_call=True,
        )
        def export_chart(_, out_path):
            if self._last_png_bytes is None:
                return dbc.Alert("Generate a chart first.", color="warning")
            if not out_path:
                return dbc.Alert("Enter an export output path first (or click Browse).",
                                 color="warning")
            try:
                os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                # Re-render with current config to honour any settings changes
                gen = CompositeChartGenerator(self._config, self._logger, self._gantt_config)
                if gen.generate(self._last_all_data_points, self._last_tasks):
                    dpi = self._config.get_chart_config().get('dpi', DEFAULT_DPI)
                    gen.fig.savefig(out_path, dpi=dpi, bbox_inches=None,
                                    facecolor='white', edgecolor='none', pad_inches=0)
                    plt.close(gen.fig)
                    self._logger.info(f"Chart exported: {out_path}")
                    return dbc.Alert(f"✓ Saved: {out_path}", color="success")
                return dbc.Alert("Export render failed — see log.", color="danger")
            except Exception as e:
                self._logger.error(f"Export error: {e}")
                return dbc.Alert(f"Export error: {e}", color="danger")

        # ── Live Preview tab: Plotly chart ────────────────────────────────────
        @app.callback(
            Output('plotly-preview', 'figure'),
            Input('store-preview-ready', 'data'),
            prevent_initial_call=True,
        )
        def update_plotly_preview(ready):
            if not ready or self._last_all_data_points is None:
                return go.Figure()
            return build_plotly_preview(
                self._config,
                self._last_all_data_points,
                self._last_tasks or [],
                self._gantt_config,
            )


        @app.callback(
            Output('data-summary-table', 'children'),
            Input('store-series-summary', 'data'),
        )
        def update_data_summary(data):
            if not data:
                return html.P("Generate a chart to see data summary.",
                              className="text-muted small")
            return dash_table.DataTable(
                data=data,
                columns=[{'name': c, 'id': c} for c in data[0].keys()],
                style_table={'overflowX': 'auto'},
                style_cell={'fontSize': '12px', 'padding': '4px 8px'},
                style_header={'fontWeight': 'bold', 'background': '#e8f4f8'},
            )

        # ── Live Preview tab: event table ─────────────────────────────────────
        @app.callback(
            Output('event-summary-table', 'children'),
            Input('store-task-summary', 'data'),
        )
        def update_event_table(data):
            if not data:
                return html.P("Generate a chart to see events.",
                              className="text-muted small")
            return dash_table.DataTable(
                data=data,
                columns=[{'name': c, 'id': c} for c in data[0].keys()],
                style_table={'overflowX': 'auto'},
                style_cell={'fontSize': '11px', 'padding': '3px 6px'},
                style_header={'fontWeight': 'bold', 'background': '#f0e8f8'},
                page_size=20,
            )

        # ── Log polling — color-coded HTML ────────────────────────────────────
        @app.callback(
            Output('log-output', 'children'),
            Input('interval-log', 'n_intervals'),
            Input('btn-clear-log', 'n_clicks'),
        )
        def update_log(_, clear_clicks):
            if ctx.triggered_id == 'btn-clear-log':
                self._log_lines.clear()
                return []
            spans = []
            for line in self._log_lines[-500:]:
                if '] WARNING:' in line:
                    cls = 'log-warning'
                elif '] ERROR:' in line or '] CRITICAL:' in line:
                    cls = 'log-error'
                elif '] DEBUG:' in line:
                    cls = 'log-debug'
                elif '] INFO:' in line:
                    cls = 'log-info'
                else:
                    cls = 'log-default'
                spans.append(html.Span(line + '\n', className=cls))
            return spans

        # ── Batch summary label ───────────────────────────────────────────────
        @app.callback(
            Output('batch-summary', 'children'),
            Input('batch-config-folder', 'value'),
            Input('batch-data-folder',   'value'),
            Input('batch-output-folder', 'value'),
        )
        def update_batch_summary(cfg_folder, data_folder, out_folder):
            def _count(folder, exts):
                if not folder or not os.path.isdir(folder):
                    return 0
                return len([f for f in os.listdir(folder)
                            if any(f.lower().endswith(e) for e in exts)])
            nc = _count(cfg_folder,  ['.json'])
            nd = _count(data_folder, ['.csv', '.txt'])
            if nc and nd and out_folder:
                return f"{nc} config(s) × {nd} data file(s) = {nc*nd} chart(s) to generate"
            parts = []
            if not nc:          parts.append("config folder")
            if not nd:          parts.append("data folder")
            if not out_folder:  parts.append("output folder")
            return f"Waiting for: {', '.join(parts)}" if parts else ""

        # ── Run batch ─────────────────────────────────────────────────────────
        @app.callback(
            Output('batch-status', 'children'),
            Output('btn-batch', 'disabled'),
            Input('btn-batch', 'n_clicks'),
            State('batch-config-folder', 'value'),
            State('batch-data-folder',   'value'),
            State('batch-output-folder', 'value'),
            State('event-file-path',     'value'),
            State('batch-workers',       'value'),
            prevent_initial_call=True,
        )
        def run_batch(_, cfg_folder, data_folder, out_folder, event_path, workers):
            errors = []
            if not self._gantt_config.is_loaded():
                errors.append("Load a Gantt config first.")
            if not event_path or not os.path.isfile(event_path):
                errors.append("Event CSV not found.")
            if not cfg_folder or not os.path.isdir(cfg_folder):
                errors.append("Config folder not found.")
            if not data_folder or not os.path.isdir(data_folder):
                errors.append("Data folder not found.")
            if not out_folder or not os.path.isdir(out_folder):
                errors.append("Output folder not found.")
            if errors:
                return dbc.Alert(" | ".join(errors), color="warning"), False

            config_files = sorted([os.path.join(cfg_folder, f)
                                   for f in os.listdir(cfg_folder)
                                   if f.lower().endswith('.json')])
            data_files   = sorted([os.path.join(data_folder, f)
                                   for f in os.listdir(data_folder)
                                   if f.lower().endswith(('.csv', '.txt'))])
            if not config_files:
                return dbc.Alert("No JSON files in config folder.", color="warning"), False
            if not data_files:
                return dbc.Alert("No CSV/TXT files in data folder.", color="warning"), False

            total     = len(config_files) * len(data_files)
            n_workers = max(1, min(16, int(workers or 4)))
            self._batch_running = True
            self._batch_result  = None
            self._batch_stop_event.clear()
            self._batch_log.clear()
            t = threading.Thread(
                target=self._batch_thread,
                args=(config_files, data_files, event_path, out_folder, total, n_workers),
                daemon=True,
            )
            t.start()
            return (
                dbc.Alert(f"⏳ Batch started — {total} charts, {n_workers} workers.",
                          color="info"),
                True,    # Run Batch disabled while running
            )

        # ── Batch log polling + status update when done ───────────────────────
        @app.callback(
            Output('batch-log-output', 'children'),
            Output('btn-batch', 'disabled', allow_duplicate=True),
            Output('btn-estop', 'disabled'),
            Output('btn-estop', 'children'),
            Output('batch-status', 'children', allow_duplicate=True),
            Input('interval-batch', 'n_intervals'),
            prevent_initial_call=True,
        )
        def poll_batch_log(_):
            # Render log lines as colored spans
            spans = []
            for line in self._batch_log[-500:]:
                if '✓' in line:
                    cls = 'log-info'
                elif '✗' in line or 'ERROR' in line or 'FAILED' in line or 'ABORTED' in line:
                    cls = 'log-error'
                elif 'WARNING' in line or 'SKIPPED' in line or '⚠' in line:
                    cls = 'log-warning'
                elif '=' * 10 in line or 'BATCH' in line:
                    cls = 'log-debug'
                else:
                    cls = 'log-default'
                spans.append(html.Span(line + '\n', className=cls))

            still_run = self._batch_running
            result    = self._batch_result
            stopped   = self._batch_stop_event.is_set()

            # btn-batch: disabled while running
            batch_disabled = still_run
            # btn-estop: enabled only while running AND not yet stopping
            estop_disabled = not still_run
            estop_label    = "⏹ Stopping…" if (still_run and stopped) else "⏹ E-Stop"

            # Status message
            if result is None:
                status = no_update
            elif result.get('failed'):
                status = dbc.Alert("✗ Batch failed — see Batch Log.", color="danger")
            elif result.get('stopped'):
                ok  = result['done'] - result['errors']
                tot = result['total']
                status = dbc.Alert(
                    f"⚠ Batch stopped — {ok}/{tot} charts saved to {result['out_folder']}",
                    color="warning")
            else:
                ok  = result['done'] - result['errors']
                tot = result['done']
                clr = "success" if result['errors'] == 0 else "warning"
                status = dbc.Alert(
                    f"✓ Batch complete — {ok}/{tot} charts saved to {result['out_folder']}",
                    color=clr)

            return spans, batch_disabled, estop_disabled, estop_label, status

        # ── Settings modal open/close ─────────────────────────────────────────
        @app.callback(
            Output('settings-modal', 'is_open'),
            Output('settings-width', 'value'),
            Output('settings-height', 'value'),
            Output('settings-dpi', 'value'),
            Output('settings-font-scale', 'value'),
            Output('settings-lw-scale', 'value'),
            Output('settings-lgw', 'value'),
            Input('btn-settings', 'n_clicks'),
            Input('btn-settings-cancel', 'n_clicks'),
            Input('btn-settings-apply', 'n_clicks'),
            State('settings-modal', 'is_open'),
            State('settings-width', 'value'),
            State('settings-height', 'value'),
            State('settings-dpi', 'value'),
            State('settings-font-scale', 'value'),
            State('settings-lw-scale', 'value'),
            State('settings-lgw', 'value'),
            prevent_initial_call=True,
        )
        def settings_modal(n_open, n_cancel, n_apply, is_open,
                           w, h, dpi, fs, lws, lgw):
            trigger = ctx.triggered_id
            cc  = self._config.get_chart_config()
            rc  = self._config.get_responsive_config()
            sp  = self._config.get_subplot_params()
            cur_dpi = cc.get('dpi', DEFAULT_DPI)
            res     = cc.get('resolution_px')
            cur_w   = int(res[0]) if res else int(cc.get('figure_size', DEFAULT_FIGURE_SIZE)[0] * cur_dpi)
            cur_h   = int(res[1]) if res else int(cc.get('figure_size', DEFAULT_FIGURE_SIZE)[1] * cur_dpi)

            if trigger == 'btn-settings':
                return (True, cur_w, cur_h, cur_dpi,
                        rc.get('font_scale_factor', 1.0),
                        rc.get('linewidth_scale_factor', 1.0),
                        sp.get('legend_width_px', 500))
            if trigger == 'btn-settings-cancel':
                return (False, cur_w, cur_h, cur_dpi,
                        rc.get('font_scale_factor', 1.0),
                        rc.get('linewidth_scale_factor', 1.0),
                        sp.get('legend_width_px', 500))
            # Apply
            try:
                nw, nh, nd = int(w), int(h), int(dpi)
                self._config.config.setdefault('chart', {}).update({
                    'dpi': nd, 'resolution_px': [nw, nh],
                    'figure_size': [nw / nd, nh / nd],
                })
                self._config.config.setdefault('responsive', {}).update({
                    'font_scale_factor':      float(fs),
                    'linewidth_scale_factor': float(lws),
                })
                self._config.config.setdefault('subplot_params', {}).update({
                    'legend_width_px': int(lgw),
                })
                self._logger.info(f"Settings applied: {nw}×{nh} px @ {nd} DPI")
            except (TypeError, ValueError, ZeroDivisionError) as e:
                self._logger.warning(f"Settings apply error: {e}")
            return (False, w, h, dpi, fs, lws, lgw)

        # ── PPT Builder ───────────────────────────────────────────────────────
        @app.callback(
            Output('ppt-build-status', 'children'),
            Output('btn-ppt-build', 'disabled'),
            Input('btn-ppt-build', 'n_clicks'),
            State('ppt-img-folder',    'value'),
            State('ppt-template',      'value'),
            State('ppt-output-folder', 'value'),
            State('ppt-filename',      'value'),
            State('ppt-dpi',           'value'),
            State('ppt-auto-resize',   'value'),
            prevent_initial_call=True,
        )
        def ppt_build(_, img_folder, template, out_folder, filename, dpi_val, auto_resize):
            if not _PPTX_AVAILABLE:
                return dbc.Alert("python-pptx not installed.", color="danger"), False
            errs = []
            if not img_folder or not os.path.isdir(img_folder):
                errs.append("Image folder not found.")
            if not template or not os.path.isfile(template):
                errs.append("Template file not found.")
            if not out_folder or not os.path.isdir(out_folder):
                errs.append("Output folder not found.")
            if not filename:
                errs.append("Enter an output filename.")
            if errs:
                return dbc.Alert(" | ".join(errs), color="warning"), False

            try:
                slide_dpi = int(dpi_val) if dpi_val else 96
            except ValueError:
                slide_dpi = 96

            safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)
            if not safe_name.lower().endswith('.pptx'):
                safe_name += '.pptx'
            out_path = os.path.join(out_folder, safe_name)

            self._ppt_running = True
            self._ppt_result  = None
            self._ppt_log_lines.clear()
            t = threading.Thread(
                target=self._ppt_build_thread,
                args=(img_folder, template, out_path, bool(auto_resize), slide_dpi),
                daemon=True,
            )
            t.start()
            return dbc.Alert("⏳ Building PPTX…  watch the log below.", color="info"), True

        # ── PPT log polling + status update when done ─────────────────────────
        @app.callback(
            Output('ppt-log-output', 'children'),
            Output('btn-ppt-build', 'disabled', allow_duplicate=True),
            Output('ppt-build-status', 'children', allow_duplicate=True),
            Input('interval-ppt', 'n_intervals'),
            prevent_initial_call=True,
        )
        def poll_ppt_log(_):
            spans = []
            for line in self._ppt_log_lines[-500:]:
                if '[INFO]' in line or '✓' in line:
                    cls = 'log-info'
                elif '[ERROR]' in line or '✗' in line:
                    cls = 'log-error'
                elif '[WARNING]' in line:
                    cls = 'log-warning'
                elif '[DEBUG]' in line:
                    cls = 'log-debug'
                else:
                    cls = 'log-default'
                spans.append(html.Span(line + '\n', className=cls))

            still_run = self._ppt_running
            result    = self._ppt_result
            if result is None:
                status = no_update
            elif result.get('success'):
                status = dbc.Alert(f"✓ PPTX saved: {result['path']}", color="success")
            else:
                status = dbc.Alert("✗ Build failed — see PPT Builder Log.", color="danger")
            return spans, still_run, status

    # ──────────────────────────────────────────────────────────────────────────
    # BACKGROUND THREADS
    # ──────────────────────────────────────────────────────────────────────────

    def _batch_thread(self, config_files, data_files, event_file, out_folder, total, n_workers=4):
        blog = self._batch_log.append
        blog("=" * 55)
        blog(f"BATCH STARTED — {total} chart(s), {n_workers} parallel workers")
        blog(f"  Data files  : {len(data_files)}")
        blog(f"  Config files: {len(config_files)}")
        blog(f"  Output      : {out_folder}")
        blog("=" * 55)

        # Load event/task data ONCE — shared across all workers (read-only)
        event_proc = EventDataProcessor(logger=self._logger)
        if not event_proc.load_csv(event_file):
            blog("ABORTED — failed to load event CSV")
            self._batch_running = False
            self._batch_result  = {'failed': True}
            return
        tasks = event_proc.get_tasks()
        blog(f"Events loaded: {len(tasks)} tasks")

        # Build all work items upfront
        work_items = []
        for data_path in data_files:
            for cfg_path in config_files:
                out_name = _build_output_filename(data_path, cfg_path)
                work_items.append((data_path, cfg_path,
                                   os.path.join(out_folder, out_name), out_name))

        done_count = 0
        errors     = []
        lock       = threading.Lock()

        def _render_one(item):
            """Worker: load data + config, render chart, save. Returns (out_name, err_or_None)."""
            data_path, cfg_path, out_path, out_name = item
            cfg_name  = os.path.basename(cfg_path)
            data_name = os.path.basename(data_path)

            cfg = ConfigManager(cfg_path)
            if not cfg.config:
                return out_name, f"SKIPPED (invalid config): {cfg_name}"

            all_dp = []
            for sc in cfg.get_all_series_configs():
                proc = SeriesDataProcessor(
                    logger=self._logger,
                    value_column=sc.get('value_column'),
                    value_column_keywords=sc.get('value_column_keywords', ['value']),
                )
                if not proc.load_data(data_path):
                    return out_name, f"FAILED (data load): {data_name}"
                pts = proc.get_data_points()
                if not pts:
                    return out_name, f"No data points: {data_name}"
                all_dp.append(pts)

            try:
                # Each worker uses its own GanttConfigManager to avoid shared color_index
                gantt_copy = GanttConfigManager(
                    self._gantt_config.config_path
                    if self._gantt_config.is_loaded() else None)
                gen = CompositeChartGenerator(cfg, self._logger, gantt_copy)
                if gen.generate(all_dp, tasks):
                    dpi = cfg.get_chart_config().get('dpi', DEFAULT_DPI)
                    gen.fig.savefig(out_path, dpi=dpi, bbox_inches=None,
                                    facecolor='white', edgecolor='none', pad_inches=0)
                    plt.close(gen.fig)
                    return out_name, None   # success
                else:
                    if gen.fig: plt.close(gen.fig)
                    return out_name, f"FAILED (chart gen): {out_name}"
            except Exception as e:
                return out_name, f"ERROR: {out_name} — {e}\n{traceback.format_exc()}"

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_render_one, item): item for item in work_items}
            stopped = False
            for future in as_completed(futures):
                # Check E-stop between completed futures
                if self._batch_stop_event.is_set() and not stopped:
                    stopped = True
                    blog("⚠ E-Stop signal received — cancelling remaining queued charts…")
                    # Cancel all not-yet-started futures
                    cancelled = sum(1 for f in futures if f.cancel())
                    blog(f"  {cancelled} queued chart(s) cancelled")

                out_name, err = future.result()
                with lock:
                    done_count += 1
                    progress = f"[{done_count}/{total}]"
                    if err:
                        blog(f"  {progress} ✗ {err}")
                        errors.append(err)
                    else:
                        blog(f"  {progress} ✓ {out_name}")

        blog("\n" + "=" * 55)
        saved = done_count - len(errors)
        if stopped:
            blog(f"BATCH STOPPED — {saved}/{done_count} charts saved (of {total} total)")
        else:
            blog(f"BATCH COMPLETE — {saved}/{done_count} charts saved")
        if errors:
            blog(f"{len(errors)} error(s):")
            for e in errors:
                blog(f"  • {e}")
        blog(f"Output: {out_folder}")
        blog("=" * 55)

        self._batch_result  = {
            'failed':     False,
            'stopped':    stopped,
            'done':       done_count,
            'total':      total,
            'errors':     len(errors),
            'out_folder': out_folder,
        }
        self._batch_running = False

    def _ppt_build_thread(self, img_folder, template, out_path, auto_resize, slide_dpi):
        plog = self._ppt_log_lines.append

        class _RelayLogger:
            def __init__(self, cb): self._cb = cb
            def info(self,    m): self._cb(f"[INFO]    {m}")
            def warning(self, m): self._cb(f"[WARNING] {m}")
            def error(self,   m): self._cb(f"[ERROR]   {m}")
            def debug(self,   m): self._cb(f"[DEBUG]   {m}")

        def _progress(cur, total, fname):
            plog(f"  Slide {cur}/{total} — {fname}")

        builder = PPTBuilder(logger=_RelayLogger(plog))
        result  = None
        try:
            result = builder.build(
                img_folder, template, out_path,
                auto_resize_slide=auto_resize,
                slide_dpi=slide_dpi,
                progress_callback=_progress,
            )
            if result:
                self._last_pptx_path = result
                plog(f"\n✓ PPTX saved: {result}")
                self._ppt_result = {'success': True, 'path': result}
            else:
                plog("\n✗ Build failed — see errors above.")
                self._ppt_result = {'success': False}
        except PPTBuilder.NoPicturePlaceholderError as e:
            plog(f"\n✗ {e}")
            self._ppt_result = {'success': False}
        except Exception as e:
            plog(f"\n✗ Unexpected error: {e}")
            plog(traceback.format_exc())
            self._ppt_result = {'success': False}
        finally:
            self._ppt_running = False

    # ──────────────────────────────────────────────────────────────────────────
    # RUN
    # ──────────────────────────────────────────────────────────────────────────

    def run(self, port: int = DASH_PORT, debug: bool = False, auto_open: bool = True):
        import webbrowser
        from threading import Timer
        print("=" * 60)
        print("  COMPOSITE DATA & GANTT PLOTTER — Dash Edition")
        print("=" * 60)
        print(f"  URL   : http://{DASH_HOST}:{port}")
        print(f"  python-pptx : {'available' if _PPTX_AVAILABLE else 'NOT INSTALLED'}")
        print("=" * 60)
        if auto_open:
            Timer(1.5, lambda: webbrowser.open(f"http://{DASH_HOST}:{port}")).start()
        self._app.run(debug=debug, port=port, host=DASH_HOST)


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Composite Data & Gantt Plotter — Dash Edition')
    parser.add_argument('--port',       type=int,            default=DASH_PORT)
    parser.add_argument('--debug',      action='store_true', default=False)
    parser.add_argument('--no-browser', action='store_true', default=False)
    args = parser.parse_args()

    DashApp().run(port=args.port, debug=args.debug, auto_open=not args.no_browser)


if __name__ == '__main__':
    main()