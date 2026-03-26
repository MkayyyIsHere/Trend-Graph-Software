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
import os
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ── third-party ───────────────────────────────────────────────────────────────
import pandas as pd



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

from utils.constants import (
    DEFAULT_GANTT_CONFIG_PATH, DEFAULT_FIGURE_SIZE,
    DEFAULT_DPI, RESOLUTION_PRESETS, DASH_PORT, DASH_HOST
)

from utils.logger import GUILogger
from backend.models import DataPoint, Task
from backend.processors import SeriesDataProcessor, EventDataProcessor
from backend.config import ConfigManager, GanttConfigManager

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.enum.shapes import PP_PLACEHOLDER
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

from backend.ppt_builder import PPTBuilder

from backend.chart_gen import CompositeChartGenerator, _build_output_filename

from backend.plotly_preview import build_plotly_figure
from backend.batch_worker import run_batch as _run_batch_worker

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
            return build_plotly_figure(
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
        def start_batch_run(_, cfg_folder, data_folder, out_folder, event_path, workers):
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
            self._batch_result = None
            self._batch_stop_event.clear()
            self._batch_log.clear()

            def _on_batch_done(result):
                self._batch_result = result
                self._batch_running = False

            t = threading.Thread(
                target=_run_batch_worker,
                args=(
                    config_files,
                    data_files,
                    event_path,
                    out_folder,
                    total,
                    n_workers,
                    self._logger,
                    self._gantt_config,
                    self._batch_log,
                    self._batch_stop_event,
                    _on_batch_done,
                ),
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