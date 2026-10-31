"""1_app/layout.py — All Dash HTML/component layout builders."""
import os

from dash import dcc, html
import dash_bootstrap_components as dbc

from utils.constants import load_settings

try:
    from pptx import Presentation  # noqa: F401
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

from app.config_manager_layout import config_manager_tab
from app.results import results_tab
from app.wizard import wizard_tab

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


# ── Reusable builders ────────────────────────────────────────────────────────

def collapsible_log_card(card_id, collapse_id, output_id, hidden_ta_id,
                         copy_btn_id, clear_btn_id, toggle_btn_id,
                         title, bg_color='#1e1e2e', height='260px', extra_style=None):
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
        ], justify="between", align="center"), className="py-1"),
        dbc.Collapse(id=collapse_id, is_open=False, children=[
            dbc.CardBody([
                html.Div(id=output_id, style=style),
                dcc.Textarea(id=hidden_ta_id,
                             style={'position': 'absolute', 'left': '-9999px',
                                    'top': 0, 'opacity': 0},
                             readOnly=True),
            ]),
        ]),
    ])


def _path_group(input_id, browse_id, placeholder, value='', browse_label="📁 Browse"):
    return dbc.InputGroup([
        dbc.Input(id=input_id, value=value, placeholder=placeholder, size='sm', debounce=True),
        dbc.Button(browse_label, id=browse_id, color='secondary', size='sm'),
    ], size='sm')


# ── Tab builders ─────────────────────────────────────────────────────────────

def _results_tab():
    batch_log = collapsible_log_card(
        'batch-log-card', 'batch-log-collapse', 'batch-log-output', 'batch-log-text-hidden',
        'btn-copy-batch-log', 'btn-clear-batch-log', 'btn-toggle-batch-log',
        'Run log', bg_color='#1e2030', height='220px',
    )
    return results_tab(batch_log)


def _ppt_tab():
    """Guided PowerPoint build: pick slides (last run by default) → template → Build."""
    ppt_log = collapsible_log_card(
        'ppt-log-card', 'ppt-log-collapse', 'ppt-log-output', 'ppt-log-text-hidden',
        'btn-copy-ppt-log', 'btn-clear-ppt-log', 'btn-toggle-ppt-log',
        'PowerPoint log', height='240px',
    )
    s = load_settings()

    slides = dbc.Card(className="mb-2", children=[
        dbc.CardHeader(html.Div([
            dbc.Badge("1", color="primary", pill=True, className="me-2"),
            html.B("Slides"),
            html.Span(id='ppt-count', className="ms-2 small text-muted"),
        ], className="d-flex align-items-center")),
        dbc.CardBody([
            dbc.RadioItems(id='ppt-source', inline=True, className="small mb-2", value='run',
                           options=[{'label': 'Images from the last run', 'value': 'run'},
                                    {'label': 'Images in a folder', 'value': 'folder'}]),
            html.Div(id='ppt-folder-row', style={'display': 'none'}, className="mb-2",
                     children=_path_group('ppt-img-folder', 'btn-browse-ppt-img',
                                          'Folder containing PNG/JPG images…')),
            html.Div([
                dbc.Button("Select all", id='ppt-all', color='link', size='sm', className="p-0 me-3"),
                dbc.Button("Select none", id='ppt-none', color='link', size='sm', className="p-0"),
                html.Small("  ·  ▲▼ sets the slide order", className="text-muted ms-2"),
            ], className="mb-1"),
            html.Div(id='ppt-image-list', className="cm-pane border rounded",
                     style={'maxHeight': '52vh', 'overflowY': 'auto'}),
            dcc.Store(id='ppt-order', data=[]),     # [{name, on}] in slide order
            dcc.Store(id='ppt-folder', data=''),    # folder the names are relative to
        ]),
    ])

    output = dbc.Card(className="mb-2", children=[
        dbc.CardHeader(html.Div([
            dbc.Badge("2", color="primary", pill=True, className="me-2"),
            html.B("Template & file"),
        ], className="d-flex align-items-center")),
        dbc.CardBody([
            dbc.Label("Template", className="small mb-1"),
            _path_group('ppt-template', 'btn-browse-ppt-tmpl',
                        'Built-in template — Browse to use your own .pptx',
                        s.get('ppt_template', ''), browse_label="Change…"),
            html.Div([
                html.Small(id='ppt-template-info', className="text-muted"),
                dbc.Button("Use built-in", id='ppt-template-default', color='link', size='sm',
                           className="p-0 ms-2"),
            ], className="mb-2"),
            dbc.Label("File name", className="small mb-1"),
            dbc.Input(id='ppt-filename', size='sm', className="mb-1"),
            html.Small(id='ppt-out-info', className="text-muted d-block mb-2"),
            dbc.Button("More options", id='ppt-more-toggle', color='link', size='sm',
                       className="p-0 mb-1"),
            dbc.Collapse(id='ppt-more', is_open=False, children=[
                dbc.Label("Save in folder (default: the images' folder)", className="small mb-1"),
                html.Div(_path_group('ppt-output-folder', 'btn-browse-ppt-out-folder',
                                     'Same folder as the images'), className="mb-2"),
                dbc.Row([
                    dbc.Col(dbc.Label("Slide DPI", className="small mb-0"), width='auto'),
                    dbc.Col(dbc.Input(id='ppt-dpi', value='96', type='number',
                                      min=72, max=600, size='sm'), width=3),
                ], className="align-items-center g-2 mb-2"),
                dbc.Checklist(id='ppt-auto-resize', className="small mb-2",
                              options=[{'label': ' Resize slides to the image shape',
                                        'value': 'yes'}],
                              value=['yes']),
            ]),
            html.Hr(className="my-2"),
            dbc.Button("📑 Build PowerPoint", id='btn-ppt-build', color='primary',
                       disabled=not _PPTX_AVAILABLE),
            html.Div(id='ppt-build-status', className="mt-2 small"),
        ]),
    ])

    return dbc.Tab(label="📑 PowerPoint", tab_id="tab-ppt", children=[
        dbc.Container(fluid=True, style={'maxWidth': '1600px'}, children=[
            dbc.Alert("python-pptx not installed. Run: pip install python-pptx",
                      color="danger", is_open=not _PPTX_AVAILABLE, className="mb-2"),
            dbc.Row([
                dbc.Col(slides, lg=7),
                dbc.Col(output, lg=5),
            ], className="g-2"),
            ppt_log,
        ]),
    ])


def _stores():
    return html.Div([
        dcc.Store(id='store-ppt-result', data=None),
        dcc.Interval(id='interval-ppt', interval=1000, n_intervals=0),
    ])


# ── Public entry point ───────────────────────────────────────────────────────

def build_layout():
    """Return the complete Dash 1_app layout."""
    header = dbc.Navbar(
        dbc.Container([
            html.Span("📊 Trend Graph", className="navbar-brand fw-bold"),
            html.Small("Power quality trend charts from analyser exports",
                       className="text-white-50"),
        ], fluid=True),
        color="primary", dark=True, className="mb-2 py-1",
    )
    return html.Div([
        html.Div(id='_css-placeholder', style={'display': 'none'}),
        header,
        dbc.Tabs(id='main-tabs', active_tab='tab-wizard', className="mb-2 px-3", children=[
            wizard_tab(), _results_tab(), _ppt_tab(), config_manager_tab(),
        ]),
        _stores(),
    ])
