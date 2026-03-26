"""1_app/layout.py — All Dash HTML/component layout builders."""
import os

from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc

from utils.constants import RESOLUTION_PRESETS, DEFAULT_DPI, DEFAULT_FIGURE_SIZE

try:
    from pptx import Presentation  # noqa: F401
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

from app.config_manager_layout import config_manager_tab

_LOG_STYLE_BASE = {
    'overflowY': 'auto', 'fontSize': '11px',
    'borderRadius': '6px', 'padding': '10px',
    'fontFamily': 'monospace', 'whiteSpace': 'pre-wrap',
    'color': 'inherit',
}


def ensure_assets():
    """Write log-color CSS into 4_assets/ so Dash auto-loads it."""
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '4_assets')
    os.makedirs(assets_dir, exist_ok=True)
    css_path = os.path.join(assets_dir, 'log_colors.css')
    if not os.path.exists(css_path):
        with open(css_path, 'w') as f:
            f.write(
                ".log-info    { color: #a6e3a1; }\n"
                ".log-warning { color: #f9e2af; }\n"
                ".log-error   { color: #f38ba8; }\n"
                ".log-debug   { color: #89b4fa; }\n"
                ".log-default { color: #cdd6f4; }\n"
            )


# ── Reusable row builders ────────────────────────────────────────────────────

def file_row(label, input_id, browse_id, upload_id, placeholder,
             extra_btn=None, width_label=2):
    """Labelled file-input row: text box + Browse button only (no drop zone).
    upload_id kept for API compatibility but no Upload component is rendered.
    """
    buttons = [
        dbc.Button("📁 Browse", id=browse_id, color='secondary', size='sm', className='me-1'),
    ]
    if extra_btn:
        buttons.append(extra_btn)
    return dbc.Row([
        dbc.Col(dbc.Label(label), width=width_label),
        dbc.Col(dbc.Input(id=input_id, placeholder=placeholder, size='sm'), width=True),
        dbc.Col(html.Div(buttons, className='d-flex align-items-center'), width='auto'),
    ], className="mb-2 align-items-center")


def folder_browse_row(label, input_id, browse_id, placeholder):
    """Folder path row with a Tkinter Browse button — no drop zone."""
    return dbc.Row([
        dbc.Col(dbc.Label(label), width=2),
        dbc.Col(dbc.Input(id=input_id, placeholder=placeholder, size='sm'), width=True),
        dbc.Col(
            dbc.Button("📁 Browse", id=browse_id, color='secondary', size='sm'),
            width='auto',
        ),
    ], className="mb-2 align-items-center")


def collapsible_log_card(card_id, collapse_id, output_id, hidden_ta_id,
                         copy_btn_id, clear_btn_id, toggle_btn_id,
                         title, bg_color='#1e1e2e', height='260px', extra_style=None):
    """Reusable collapsible log card."""
    style = {**_LOG_STYLE_BASE, 'height': height, 'background': bg_color}
    if extra_style:
        style.update(extra_style)
    return dbc.Card(className="mb-3", id=card_id, children=[
        dbc.CardHeader(dbc.Row([
            dbc.Col(html.B(title), width="auto"),
            dbc.Col([
                dbc.Button("Copy",     id=copy_btn_id,   size='sm', color='info',
                           outline=True, className='me-1'),
                dbc.Button("Clear",    id=clear_btn_id,  size='sm', color='secondary',
                           outline=True, className='me-1'),
                dbc.Button("Show Log", id=toggle_btn_id, size='sm', color='secondary', outline=True),
            ], className='ms-auto d-flex align-items-center', width='auto'),
        ], justify="between", align="center")),
        dbc.Collapse(id=collapse_id, is_open=False, children=[
            dbc.CardBody([
                html.Div(id=output_id, style=style),
                html.Textarea(id=hidden_ta_id,
                              style={'position': 'absolute', 'left': '-9999px',
                                     'top': 0, 'opacity': 0},
                              readOnly=True),
            ]),
        ]),
    ])


# ── Tab builders ─────────────────────────────────────────────────────────────

def _chart_tab():
    log_panel = collapsible_log_card(
        'log-card', 'log-collapse', 'log-output', 'log-text-hidden',
        'btn-copy-log', 'btn-clear-log', 'btn-toggle-log', 'Log',
    )

    # remove extra_style={'color': '#c3e88d'} from the batch_log call
    batch_log = collapsible_log_card(
        'batch-log-card', 'batch-log-collapse', 'batch-log-output', 'batch-log-text-hidden',
        'btn-copy-batch-log', 'btn-clear-batch-log', 'btn-toggle-batch-log',
        'Batch Progress Log', bg_color='#1e2030', height='220px',
    )

    return dbc.Tab(label="📊 Chart Plotter", tab_id="tab-chart", children=[
        dbc.Container(fluid=True, children=[
            # Gantt / Event
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(html.B("Gantt / Event Overlay")),
                dbc.CardBody([
                    file_row("Gantt Config (.json):", 'gantt-config-path',
                             'btn-browse-gantt', 'upload-gantt', 'e.g. config_gantt.json'),
                    html.Div(id='gantt-config-status', className="text-muted small mb-2"),
                    html.Hr(className="my-2"),
                    file_row("Event / Task CSV:", 'event-file-path',
                             'btn-browse-event', 'upload-event', 'Path to event CSV…',
                             extra_btn=dbc.Button("Preview", id='btn-preview-events',
                                                  color='info', size='sm', outline=True)),
                ]),
            ]),
            # Single chart
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(html.B("Single Chart")),
                dbc.CardBody([
                    file_row("Plot Config (.json):", 'plot-config-path',
                             'btn-browse-config', 'upload-config', 'Path to plot config JSON…'),
                    html.Div(id='plot-config-status', className="text-muted small mb-2"),
                    html.Hr(className="my-2"),
                    file_row("Series Data File:", 'series-file-path',
                             'btn-browse-series', 'upload-series', 'Path to CSV / TXT data…',
                             extra_btn=dbc.Button("Preview", id='btn-preview-series',
                                                  color='info', size='sm', outline=True)),
                    dbc.Row([
                        dbc.Col(dbc.Label("Export Output:"), width=2),
                        dbc.Col(dbc.Input(id='export-output-path',
                                         placeholder='Full path for saved PNG/PDF/SVG…',
                                         size='sm'), width=True),
                        dbc.Col(dbc.Button("📁 Browse", id='btn-browse-export',
                                           color='secondary', size='sm'), width='auto'),
                    ], className="mb-2 align-items-center"),
                    dbc.Row([dbc.Col([
                        dbc.Button("▶ Generate Chart", id='btn-generate', color='primary', className='me-2'),
                        dbc.Button("💾 Export Chart",  id='btn-export',   color='success', className='me-2', disabled=True),
                        dbc.Button("⚙ Settings",       id='btn-settings', color='secondary', outline=True),
                    ], className="mt-2")]),
                    html.Div(id='generate-status', className="mt-2 small"),
                ]),
            ]),
            # Batch
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(html.B("Batch Processing")),
                dbc.CardBody([
                    folder_browse_row("Config Folder:", 'batch-config-folder',
                                      'btn-browse-batch-config', 'Folder of plot config JSONs…'),
                    folder_browse_row("Data Folder:",   'batch-data-folder',
                                      'btn-browse-batch-data',   'Folder of CSV / TXT data files…'),
                    folder_browse_row("Output Folder:", 'batch-output-folder',
                                      'btn-browse-batch-output', 'Output folder for exported PNGs…'),
                    html.Div(id='batch-summary', className="text-primary small mb-2"),
                    dbc.Row([dbc.Col([
                        dbc.Button("▶ Run Batch", id='btn-batch', color='warning', className='me-2'),
                        dbc.Button("⏹ E-Stop",   id='btn-estop', color='danger', disabled=True,
                                   title='Stop batch after current charts finish'),
                    ], className='d-flex align-items-center')]),
                    html.Div(id='batch-status', className="mt-2 small"),
                ]),
            ]),
            batch_log,
            log_panel,
        ]),
    ])


def _preview_tab():
    return dbc.Tab(label="🔍 Live Preview", tab_id="tab-preview", children=[
        dbc.Container(fluid=True, children=[
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(html.B("Interactive Chart Preview")),
                dbc.CardBody(dcc.Graph(
                    id='plotly-preview', style={'height': '500px'},
                    config={'displayModeBar': True, 'scrollZoom': True,
                            'toImageButtonOptions': {'format': 'png',
                                                     'filename': 'composite_preview',
                                                     'height': 900, 'width': 1600, 'scale': 2}},
                )),
            ]),
            dbc.Row([
                dbc.Col(dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("Data Summary")),
                    dbc.CardBody(html.Div(id='data-summary-table')),
                ]), width=5),
                dbc.Col(dbc.Card(className="mb-3", children=[
                    dbc.CardHeader(html.B("Event / Task Table")),
                    dbc.CardBody(html.Div(id='event-summary-table',
                                          style={'maxHeight': '280px', 'overflowY': 'auto'})),
                ]), width=7),
            ]),
        ]),
    ])


def _ppt_tab():
    ppt_log = collapsible_log_card(
        'ppt-log-card', 'ppt-log-collapse', 'ppt-log-output', 'ppt-log-text-hidden',
        'btn-copy-ppt-log', 'btn-clear-ppt-log', 'btn-toggle-ppt-log',
        'PPT Builder Log', height='300px',
    )
    return dbc.Tab(label="📑 PPT Builder", tab_id="tab-ppt", children=[
        dbc.Container(fluid=True, children=[
            dbc.Alert("python-pptx not installed. Run: pip install python-pptx",
                      color="danger", is_open=not _PPTX_AVAILABLE, className="mb-3"),
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(html.B("PowerPoint Builder")),
                dbc.CardBody([
                    folder_browse_row("Image Folder:",  'ppt-img-folder',
                                      'btn-browse-ppt-img', 'Folder containing PNG/JPG images…'),
                    file_row("PPTX Template:",        'ppt-template',
                             'btn-browse-ppt-tmpl',   'upload-ppt-tmpl-file',
                             'Path to .pptx template…'),
                    folder_browse_row("Output Folder:", 'ppt-output-folder',
                                      'btn-browse-ppt-out-folder', 'Output folder for .pptx…'),
                    dbc.Row([
                        dbc.Col(dbc.Label("Output Filename:"), width=3),
                        dbc.Col(dbc.Input(id='ppt-filename', value='output.pptx', size='sm'), width=5),
                        dbc.Col(dbc.Label("DPI:"), width=1),
                        dbc.Col(dbc.Input(id='ppt-dpi', value='96', type='number',
                                         min=72, max=600, size='sm'), width=3),
                    ], className="mb-2 align-items-center"),
                    dbc.Checklist(id='ppt-auto-resize', className="mb-2",
                                  options=[{'label': ' Auto-resize slide canvas to image dimensions',
                                            'value': 'yes'}],
                                  value=['yes']),
                    dbc.Button("📑 Build PPTX", id='btn-ppt-build', color='primary',
                               disabled=not _PPTX_AVAILABLE),
                    html.Div(id='ppt-build-status', className="mt-2 small"),
                ]),
            ]),
            ppt_log,
        ]),
    ])


def _settings_modal():
    return dbc.Modal(id='settings-modal', size='lg', is_open=False, children=[
        dbc.ModalHeader(dbc.ModalTitle("Chart Settings & Layout")),
        dbc.ModalBody([
            dbc.Row([dbc.Col([
                dbc.Label("Resolution Preset"),
                dbc.Select(id='preset-select',
                           options=[{'label': k, 'value': k} for k in RESOLUTION_PRESETS],
                           value="2560×1440 (2K/QHD)  ← default"),
            ], width=12, className="mb-3")]),
            dbc.Row([
                dbc.Col([dbc.Label("Width (px)"),
                         dbc.Input(id='settings-width',  value='2560', type='number', min=320,  max=7680)], width=3),
                dbc.Col([dbc.Label("Height (px)"),
                         dbc.Input(id='settings-height', value='1440', type='number', min=240,  max=4320)], width=3),
                dbc.Col([dbc.Label("DPI"),
                         dbc.Input(id='settings-dpi',    value='96',   type='number', min=72,   max=1200)], width=3),
                dbc.Col([dbc.Label("Font Scale"),
                         dbc.Input(id='settings-font-scale', value='1.0', type='number',
                                   min=0.5, max=3.0, step=0.1)], width=3),
            ], className="mb-3"),
            dbc.Row([
                dbc.Col([dbc.Label("Linewidth Scale"),
                         dbc.Input(id='settings-lw-scale', value='1.0', type='number',
                                   min=0.5, max=3.0, step=0.1)], width=3),
                dbc.Col([dbc.Label("Legend Width (px)"),
                         dbc.Input(id='settings-lgw', value='500', type='number',
                                   min=100, max=2000, step=10)], width=3),
                dbc.Col([dbc.Label("Subplot Left"),
                         dbc.Input(id='settings-left', value='0.03', type='number',
                                   min=0.0, max=0.5, step=0.01)], width=3),
                dbc.Col([dbc.Label("Subplot Bottom"),
                         dbc.Input(id='settings-bottom', value='0.06', type='number',
                                   min=0.0, max=0.5, step=0.01)], width=3),
            ], className="mb-3"),
            html.Hr(className="my-2"),
            dbc.Row([dbc.Col([
                dbc.Label("Parallel Workers (Batch)"),
                dbc.Input(id='batch-workers', value='4', type='number', min=1, max=16),
                html.Small("Number of charts rendered simultaneously during batch runs.",
                           className="text-muted"),
            ], width=4, className="mb-3")]),
        ]),
        dbc.ModalFooter([
            dbc.Button("Apply",  id='btn-settings-apply',  color='primary',   className='me-2'),
            dbc.Button("Cancel", id='btn-settings-cancel', color='secondary'),
        ]),
    ])


def _data_preview_modal():
    return dbc.Modal(id='data-preview-modal', size='xl', is_open=False, children=[
        dbc.ModalHeader(dbc.ModalTitle(id='data-preview-title', children="Preview")),
        dbc.ModalBody(html.Div(id='data-preview-content',
                               style={'overflowX': 'auto', 'maxHeight': '70vh', 'overflowY': 'auto'})),
        dbc.ModalFooter(dbc.Button("Close", id='btn-close-preview', color='secondary')),
    ])


def _stores():
    return html.Div([
        dcc.Store(id='store-config-loaded',  data=False),
        dcc.Store(id='store-gantt-loaded',   data=False),
        dcc.Store(id='store-preview-ready',  data=False),
        dcc.Store(id='store-series-summary', data=None),
        dcc.Store(id='store-task-summary',   data=None),
        dcc.Store(id='store-batch-result',   data=None),
        dcc.Store(id='store-ppt-result',     data=None),
        dcc.Interval(id='interval-log',   interval=800,  n_intervals=0),
        dcc.Interval(id='interval-batch', interval=1000, n_intervals=0),
        dcc.Interval(id='interval-ppt',   interval=1000, n_intervals=0),
        dcc.Download(id='download-chart'),
    ])


# ── Public entry point ───────────────────────────────────────────────────────

def build_layout():
    """Return the complete Dash 1_app layout."""
    header = dbc.Navbar(
        dbc.Container([
            html.Span("📊 Composite Data & Gantt Plotter", className="navbar-brand fw-bold"),
            html.Small(" — Dash Edition", className="text-muted"),
        ], fluid=True),
        color="primary", dark=True, className="mb-3",
    )
    return html.Div([
        html.Div(id='_css-placeholder', style={'display': 'none'}),
        header,
        dbc.Tabs(id='main-tabs', active_tab='tab-chart', className="mb-3 px-3", children=[
            _chart_tab(), _preview_tab(), _ppt_tab(), config_manager_tab(),
        ]),
        _settings_modal(),
        _data_preview_modal(),
        _stores(),
    ])