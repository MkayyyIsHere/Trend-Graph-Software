"""1_app/wizard.py — 🚀 Quick Run: 3-step wizard (Events → Data → Generate & Export).

Everything a normal run needs lives on this one tab:
  1. Events  — the test-schedule CSV; the plot time window is derived from it
  2. Data    — folder of analyser exports
  3. Output  — output folder, which charts to draw, and their Y limits

Folders, the event file, chart selection and Y limits are remembered in
%APPDATA%/TrendGraph/settings.json, so a repeat run is: open app → Generate.
The bundled default charts are used unless a custom config folder has been
chosen in the Advanced → Config Manager tab.
"""
import io
import os
import re
import threading
import zipfile
from datetime import datetime

from dash import Input, Output, State, ALL, ctx, html, dcc, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from flask import send_file

from utils.constants import (
    DEFAULT_CONFIGS_DIR, DEFAULT_PPT_TEMPLATE_PATH, RESERVED_CONFIG_FILENAMES,
    load_settings, save_settings,
)
from backend.batch_profile import BatchProfileManager
from backend.batch_worker import run_batch as _run_batch_worker
from backend.config import ConfigManager
from backend.formats import SYSTEMS, sniff_brand
from backend.processors import EventDataProcessor, event_plot_window

_DATA_EXTS   = ('.csv', '.txt')
_WINDOW_FMT  = '%Y-%m-%d %H:%M'


# ── Helpers ──────────────────────────────────────────────────────────────────

def _config_folder() -> str:
    """Custom config folder from Config Manager if valid, else bundled defaults."""
    folder = load_settings().get('last_config_folder', '')
    if folder and os.path.isdir(folder) and any(
            f.lower().endswith('.json') and f not in RESERVED_CONFIG_FILENAMES
            for f in os.listdir(folder)):
        return folder
    return DEFAULT_CONFIGS_DIR


def _aesthetics_for(folder: str):
    path = os.path.join(folder, 'aesthetics.json')
    return path if os.path.isfile(path) else None


def _chart_entries(folder: str) -> list:
    """[{file, name, included, y_min, y_max}] in batch-profile order."""
    bpm = BatchProfileManager()
    bpm.load(folder)
    entries = []
    for e in bpm.merge_with_folder(folder):
        cfg  = ConfigManager(os.path.join(folder, e['filename']),
                             aesthetics_path=_aesthetics_for(folder))
        axis = cfg.get_axis_config()
        entries.append({
            'file':     e['filename'],
            'name':     os.path.splitext(e['filename'])[0],
            'included': e['included'],
            'y_min':    axis.get('y_min'),
            'y_max':    axis.get('y_max'),
        })
    return entries


def _data_files(folder: str) -> list:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.lower().endswith(_DATA_EXTS))


def _parse_window_value(text):
    for fmt in (_WINDOW_FMT, '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M'):
        try:
            return datetime.strptime((text or '').strip(), fmt)
        except ValueError:
            continue
    return None


def _num(v):
    try:
        return float(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _step_card(number, title, body, status_id):
    return dbc.Card(className="mb-3", children=[
        dbc.CardHeader(html.Div([
            dbc.Badge(str(number), color="primary", pill=True, className="me-2"),
            html.B(title),
            html.Span(id=status_id, className="ms-2"),
        ], className="d-flex align-items-center")),
        dbc.CardBody(body),
    ])


def _path_row(input_id, browse_id, placeholder, value):
    return dbc.InputGroup([
        dbc.Input(id=input_id, value=value, placeholder=placeholder, size='sm',
                  debounce=True),
        dbc.Button("📁 Browse", id=browse_id, color='secondary', size='sm'),
    ], size='sm', className="mb-2")


def _ok(text):   return dbc.Badge(f"✓ {text}", color="success")
def _todo(text): return dbc.Badge(text, color="secondary")
def _bad(text):  return dbc.Badge(f"✗ {text}", color="danger")


# ── Layout ───────────────────────────────────────────────────────────────────

def wizard_tab():
    s = load_settings()

    step1 = _step_card(1, "Test schedule (events)", [
        _path_row('wz-event-path', 'wz-browse-event',
                  'Select the test schedule (.csv or .xlsx)…', s.get('wz_event_path', '')),
        html.Div(id='wz-event-info', className="small text-muted mb-2"),
        dbc.Row([
            dbc.Col(dbc.Label("Plot from", className="small mb-0"), width='auto'),
            dbc.Col(dbc.Input(id='wz-x-min', size='sm', placeholder='YYYY-MM-DD HH:MM'), width=3),
            dbc.Col(dbc.Label("to", className="small mb-0"), width='auto'),
            dbc.Col(dbc.Input(id='wz-x-max', size='sm', placeholder='YYYY-MM-DD HH:MM'), width=3),
            dbc.Col(html.Small("Filled in from the schedule (±30 min). Edit if needed.",
                               className="text-muted"), width=True),
        ], className="align-items-center g-2"),
    ], 'wz-step1-badge')

    step2 = _step_card(2, "Analyser data", [
        _path_row('wz-data-folder', 'wz-browse-data',
                  'Folder with the analyser exports (.csv / .txt)…', s.get('wz_data_folder', '')),
        dbc.Row([
            dbc.Col(dbc.Label("System wiring", className="small mb-0"), width='auto'),
            dbc.Col(dbc.RadioItems(
                id='wz-system', inline=True, className="small",
                options=[{'label': '3-phase 4-wire (with N)',    'value': '3P4W'},
                         {'label': '3-phase 3-wire (without N)', 'value': '3P3W'}],
                value=s.get('wz_system', '3P4W') if s.get('wz_system') in SYSTEMS else '3P4W',
            )),
        ], className="align-items-center mb-1 g-2"),
        html.Small("Voltage and THD charts show phase-to-neutral (AN/BN/CN) for 4-wire, "
                   "line-to-line (AB/BC/CA) for 3-wire.", className="text-muted d-block mb-2"),
        html.Div(id='wz-data-info', className="small"),
    ], 'wz-step2-badge')

    step3 = _step_card(3, "Charts & output", [
        _path_row('wz-output-folder', 'wz-browse-output',
                  'Folder to save the chart images in…', s.get('wz_output_folder', '')),
        html.Div(id='wz-chart-source', className="small text-muted mb-2"),
        html.Div(id='wz-chart-table', className="mb-2"),
        html.Div([
            dbc.Button("↺ Reset Y limits", id='wz-reset-y', color='link', size='sm',
                       className="p-0"),
        ], className="mb-3"),
        html.Div([
            dbc.Button("▶ Generate charts", id='wz-run', color='primary', className='me-2',
                       disabled=True),
            dbc.Button("⏹ Stop", id='wz-stop', color='danger', outline=True, disabled=True),
        ], className="d-flex align-items-center mb-2"),
        html.Div(id='wz-run-hint', className="small text-muted mb-2"),
        html.Div(id='wz-progress-wrap', style={'display': 'none'}, children=[
            dbc.Progress(id='wz-progress', value=0, striped=True, animated=True,
                         style={'height': '20px'}),
            html.Small(id='wz-progress-label', className="text-muted"),
        ]),
        html.Div(id='wz-results', className="mt-3"),
    ], 'wz-step3-badge')

    return dbc.Tab(label="🚀 Quick Run", tab_id="tab-wizard", children=[
        dbc.Container(fluid=True, style={'maxWidth': '1100px'}, children=[
            step1, step2, step3,
            dcc.Store(id='wz-y-defaults'),     # {file: [y_min, y_max]} from chart configs
            dcc.Store(id='wz-run-token'),      # bumps when a run finishes (results refresh)
            dcc.Interval(id='wz-interval', interval=1000, disabled=True),
        ]),
    ])


def _chart_table(entries, saved_limits, saved_included):
    header = html.Thead(html.Tr([
        html.Th("Draw", style={'width': '60px'}), html.Th("Chart"),
        html.Th("Y min", style={'width': '140px'}), html.Th("Y max", style={'width': '140px'}),
        html.Th("Auto Y", style={'width': '80px'}),
    ]))
    rows = []
    for e in entries:
        f      = e['file']
        lim    = saved_limits.get(f, {})
        y_min  = lim.get('y_min', e['y_min'])
        y_max  = lim.get('y_max', e['y_max'])
        auto   = lim.get('auto', y_min is None or y_max is None)
        on     = (f in saved_included) if saved_included is not None else e['included']
        rows.append(html.Tr([
            html.Td(dbc.Checkbox(id={'type': 'wz-on', 'file': f}, value=on)),
            html.Td(e['name']),
            html.Td(dbc.Input(id={'type': 'wz-ymin', 'file': f}, type='number', size='sm',
                              value=y_min, disabled=auto)),
            html.Td(dbc.Input(id={'type': 'wz-ymax', 'file': f}, type='number', size='sm',
                              value=y_max, disabled=auto)),
            html.Td(dbc.Switch(id={'type': 'wz-yauto', 'file': f}, value=auto)),
        ]))
    return dbc.Table([header, html.Tbody(rows)], size='sm', bordered=False, hover=True,
                     className="mb-0 align-middle")


# ── Callbacks ────────────────────────────────────────────────────────────────

def register_wizard_callbacks(app, state):

    # ── Browse buttons (same Flask picker endpoints as the Advanced tabs) ────
    for btn_id, inp_id, url in [
        ('wz-browse-event',  'wz-event-path',    '/api/pick-file?kind=events&save=false'),
        ('wz-browse-data',   'wz-data-folder',   '/api/pick-folder?title=Select%20Data%20Folder'),
        ('wz-browse-output', 'wz-output-folder', '/api/pick-folder?title=Select%20Output%20Folder'),
    ]:
        app.clientside_callback(
            f"""
            function(n) {{
                if (!n) return window.dash_clientside.no_update;
                return fetch('{url}').then(r => r.json())
                    .then(d => d.path || window.dash_clientside.no_update);
            }}
            """,
            Output(inp_id, 'value', allow_duplicate=True),
            Input(btn_id, 'n_clicks'),
            prevent_initial_call=True,
        )

    # ── Step 1: events → summary + derived time window ───────────────────────
    @app.callback(
        Output('wz-event-info', 'children'),
        Output('wz-step1-badge', 'children'),
        Output('wz-x-min', 'value'),
        Output('wz-x-max', 'value'),
        Input('wz-event-path', 'value'),
    )
    def load_events(path):
        if not path:
            return "", _todo("not set"), no_update, no_update
        if not os.path.isfile(path):
            return "", _bad("file not found"), no_update, no_update
        proc = EventDataProcessor()
        if not proc.load_csv(path) or not proc.get_tasks():
            return ("Could not read any events — check the columns "
                    "(Test Description, Test ID, Date, Start Time, End Time).",
                    _bad("invalid schedule"), no_update, no_update)
        save_settings(wz_event_path=path)
        tasks  = proc.get_tasks()
        lo, hi = event_plot_window(tasks)
        ids    = sorted({t.display_id for t in tasks})
        info   = (f"{len(tasks)} events ({', '.join(ids[:12])}{'…' if len(ids) > 12 else ''}) · "
                  f"{min(t.start_time for t in tasks):%d %b %H:%M} → "
                  f"{max(t.end_time for t in tasks):%d %b %H:%M}")
        return info, _ok(f"{len(tasks)} events"), lo.strftime(_WINDOW_FMT), hi.strftime(_WINDOW_FMT)

    # ── Step 2: data folder ──────────────────────────────────────────────────
    @app.callback(
        Output('wz-data-info', 'children'),
        Output('wz-step2-badge', 'children'),
        Input('wz-data-folder', 'value'),
    )
    def check_data(folder):
        if not folder:
            return "", _todo("not set")
        if not os.path.isdir(folder):
            return "", _bad("folder not found")
        files = _data_files(folder)
        if not files:
            return (html.Span("No .csv / .txt files in this folder.", className="text-danger"),
                    _bad("no data files"))
        save_settings(wz_data_folder=folder)
        brands = [sniff_brand(f) for f in files]
        colour = {'Fluke': 'warning', 'Hioki': 'info'}
        chips  = [dbc.Badge([html.B(b + " "), os.path.basename(f)],
                            color=colour.get(b, 'danger'), text_color='dark' if b in colour else None,
                            className="me-1 mb-1",
                            title=None if b in colour else "Unrecognised export format")
                  for f, b in list(zip(files, brands))[:40]]
        more   = [html.Small(f" …and {len(files) - 40} more")] if len(files) > 40 else []
        unknown = brands.count('Unknown')
        note   = [html.Div(f"⚠ {unknown} file(s) not recognised as Fluke or Hioki exports — "
                           "they may fail to plot.", className="text-danger mt-1")] if unknown else []
        return html.Div(chips + more + note), _ok(f"{len(files)} file(s)")

    @app.callback(Output('wz-system', 'className'), Input('wz-system', 'value'))
    def remember_system(system):
        if system in SYSTEMS:
            save_settings(wz_system=system)
        return "small"

    # ── Step 3: chart table (refreshes when Config Manager folder/profile changes)
    @app.callback(
        Output('wz-chart-table', 'children'),
        Output('wz-chart-source', 'children'),
        Output('wz-y-defaults', 'data'),
        Input('main-tabs', 'active_tab'),
        Input('wz-reset-y', 'n_clicks'),
    )
    def build_chart_table(active_tab, _reset):
        if active_tab != 'tab-wizard' and ctx.triggered_id == 'main-tabs':
            raise PreventUpdate
        folder  = _config_folder()
        entries = _chart_entries(folder)
        s       = load_settings()
        limits  = s.get('wz_y_limits', {})
        if ctx.triggered_id == 'wz-reset-y':
            limits = {}
            save_settings(wz_y_limits={})
        included = s.get('wz_charts')
        source = ("Using built-in charts." if folder == DEFAULT_CONFIGS_DIR else
                  f"Using custom charts from {folder} (change in Advanced → Config Manager).")
        defaults = {e['file']: [e['y_min'], e['y_max']] for e in entries}
        return _chart_table(entries, limits, included), source, defaults

    # Auto-Y switch greys out its row's inputs
    @app.callback(
        Output({'type': 'wz-ymin', 'file': ALL}, 'disabled'),
        Output({'type': 'wz-ymax', 'file': ALL}, 'disabled'),
        Input({'type': 'wz-yauto', 'file': ALL}, 'value'),
    )
    def toggle_auto(autos):
        return list(autos), list(autos)

    # ── Readiness: enable Generate once all three steps are valid ────────────
    @app.callback(
        Output('wz-run', 'disabled'),
        Output('wz-run-hint', 'children'),
        Output('wz-step3-badge', 'children'),
        Input('wz-step1-badge', 'children'),
        Input('wz-step2-badge', 'children'),
        Input('wz-output-folder', 'value'),
        Input({'type': 'wz-on', 'file': ALL}, 'value'),
        Input('wz-interval', 'disabled'),
        State('wz-event-path', 'value'),
        State('wz-data-folder', 'value'),
    )
    def readiness(_b1, _b2, out_folder, ons, _idle, event_path, data_folder):
        missing = []
        if not (event_path and os.path.isfile(event_path)): missing.append("an event file")
        if not _data_files(data_folder):                     missing.append("a data folder")
        if not out_folder:                                   missing.append("an output folder")
        n_charts = sum(bool(v) for v in ons)
        if not n_charts:                                     missing.append("at least one chart")
        if out_folder:
            save_settings(wz_output_folder=out_folder)
        badge = _ok(f"{n_charts} chart(s)") if n_charts and out_folder else _todo("not set")
        if state.batch_running:
            return True, "A run is in progress…", badge
        if missing:
            return True, "Still needed: " + ", ".join(missing) + ".", badge
        n_files = len(_data_files(data_folder))
        return False, f"Will draw {n_charts} chart(s) × {n_files} file(s) = {n_charts * n_files} image(s).", badge

    # ── Run ──────────────────────────────────────────────────────────────────
    @app.callback(
        Output('wz-interval', 'disabled'),
        Output('wz-results', 'children', allow_duplicate=True),
        Input('wz-run', 'n_clicks'),
        State('wz-event-path', 'value'),
        State('wz-data-folder', 'value'),
        State('wz-output-folder', 'value'),
        State('wz-x-min', 'value'),
        State('wz-x-max', 'value'),
        State({'type': 'wz-on', 'file': ALL}, 'value'),
        State({'type': 'wz-on', 'file': ALL}, 'id'),
        State({'type': 'wz-ymin', 'file': ALL}, 'value'),
        State({'type': 'wz-ymax', 'file': ALL}, 'value'),
        State({'type': 'wz-yauto', 'file': ALL}, 'value'),
        State('batch-workers', 'value'),
        State('wz-system', 'value'),
        prevent_initial_call=True,
    )
    def run(_, event_path, data_folder, out_folder, x_min, x_max,
            ons, ids, ymins, ymaxs, autos, workers, system):
        if state.batch_running:
            raise PreventUpdate

        lo, hi = _parse_window_value(x_min), _parse_window_value(x_max)
        if (x_min or x_max) and not (lo and hi and lo < hi):
            return True, dbc.Alert("The plot window is not valid — use YYYY-MM-DD HH:MM, "
                                   "with 'from' before 'to'.", color="warning")
        try:
            os.makedirs(out_folder, exist_ok=True)
        except OSError as e:
            return True, dbc.Alert(f"Cannot create output folder: {e}", color="danger")

        folder = _config_folder()
        files  = [i['file'] for i in ids]
        limits, overrides = {}, {}
        for f, auto, ymin, ymax in zip(files, autos, ymins, ymaxs):
            ymin, ymax = _num(ymin), _num(ymax)
            limits[f] = {'auto': bool(auto), 'y_min': ymin, 'y_max': ymax}
            overrides[f] = ({'y_min': None, 'y_max': None} if auto or ymin is None or ymax is None
                            else {'y_min': ymin, 'y_max': ymax})
        chosen = [f for f, on in zip(files, ons) if on]
        save_settings(wz_y_limits=limits, wz_charts=chosen)

        config_files = [os.path.join(folder, f) for f in chosen]
        data_files   = _data_files(data_folder)
        total        = len(config_files) * len(data_files)
        x_window     = ((lo.strftime('%Y-%m-%d %H:%M:%S'), hi.strftime('%Y-%m-%d %H:%M:%S'))
                        if lo and hi else None)

        state.batch_running = True
        state.batch_result  = None
        state.batch_stop_event.clear()
        state.batch_log.clear()

        def _done(result):
            state.batch_result  = result
            state.batch_running = False

        threading.Thread(
            target=_run_batch_worker,
            args=(config_files, data_files, event_path, out_folder, total,
                  max(1, min(16, int(workers or 4))), state.logger, state.gantt_config,
                  state.batch_log, state.batch_stop_event, _done, None),
            kwargs={'aesthetics_path': _aesthetics_for(folder),
                    'axis_overrides':  overrides,
                    'x_window':        x_window,
                    'system':          system or '3P4W'},
            daemon=True,
        ).start()
        return False, ""

    @app.callback(
        Output('wz-results', 'children', allow_duplicate=True),
        Input('wz-stop', 'n_clicks'),
        prevent_initial_call=True,
    )
    def stop(_):
        if state.batch_running:
            state.batch_stop_event.set()
        return no_update

    # ── Progress polling ─────────────────────────────────────────────────────
    @app.callback(
        Output('wz-progress-wrap', 'style'),
        Output('wz-progress', 'value'),
        Output('wz-progress', 'label'),
        Output('wz-progress', 'color'),
        Output('wz-progress-label', 'children'),
        Output('wz-stop', 'disabled'),
        Output('wz-interval', 'disabled', allow_duplicate=True),
        Output('wz-run-token', 'data'),
        Input('wz-interval', 'n_intervals'),
        prevent_initial_call=True,
    )
    def poll(_):
        log   = list(state.batch_log)
        done  = sum(1 for l in log if '] ✓' in l or '] ✗' in l or '] ↷' in l)
        fails = sum(1 for l in log if '] ✗' in l)
        total = 0
        for line in log:
            m = re.search(r'BATCH STARTED — (\d+) chart', line)
            if m:
                total = int(m.group(1))
                break
        pct     = int(done / total * 100) if total else 0
        running = state.batch_running
        color   = 'danger' if state.batch_stop_event.is_set() else ('primary' if running else 'success')
        label   = (f"Drawing… {done}/{total}" if running else f"Finished {done}/{total}") + \
                  (f" — {fails} failed" if fails else "")
        token   = no_update if running else datetime.now().isoformat()
        return ({'display': 'block'}, pct, f"{pct}%", color, label,
                not running, not running, token)

    # ── Results panel: Open folder / Build PowerPoint / Download ZIP ─────────
    @app.callback(
        Output('wz-results', 'children'),
        Input('wz-run-token', 'data'),
        prevent_initial_call=True,
    )
    def show_results(_):
        r = state.batch_result
        if not r:
            raise PreventUpdate
        if r.get('failed'):
            return dbc.Alert("The run failed — the event file could not be read. "
                             "Open Advanced → Single Chart & Batch to see the log.", color="danger")
        n_ok = len(r.get('outputs', []))
        head = (f"⚠ Stopped — {n_ok} image(s) saved." if r.get('stopped') else
                f"✓ Done — {n_ok} image(s) saved to {r['out_folder']}")
        if r.get('errors'):
            head += f"  ({r['errors']} failed — see the batch log in Advanced.)"
        notes = [html.Div(f"⚠ {w}", className="small") for w in r.get('warnings', [])]
        warn  = notes[:5] + ([html.Details([html.Summary(f"…{len(notes) - 5} more note(s)",
                                                        className="small"), *notes[5:]])]
                             if len(notes) > 5 else [])
        return dbc.Alert([
            html.Div(head, className="mb-2"),
            *warn,
            dbc.Button("📂 Open folder", id='wz-open-folder', color='secondary', size='sm',
                       className='me-2'),
            dbc.Button("📑 Build PowerPoint", id='wz-build-ppt', color='primary', size='sm',
                       className='me-2', disabled=not n_ok),
            html.A(dbc.Button("⬇ Download ZIP", color='success', size='sm', disabled=not n_ok),
                   href='/api/wizard/zip', download=True),
            html.Div(id='wz-ppt-status', className="mt-2"),
            dcc.Interval(id='wz-ppt-interval', interval=1000, disabled=True),
        ], color='success' if not (r.get('errors') or r.get('stopped') or warn) else 'warning')

    @app.callback(
        Output('wz-ppt-status', 'children', allow_duplicate=True),
        Input('wz-open-folder', 'n_clicks'),
        prevent_initial_call=True,
    )
    def open_folder(_):
        r = state.batch_result or {}
        try:
            os.startfile(r.get('out_folder', ''))
        except Exception as e:
            return html.Small(f"Could not open folder: {e}", className="text-danger")
        return no_update

    @app.callback(
        Output('wz-ppt-status', 'children'),
        Output('wz-ppt-interval', 'disabled'),
        Output('wz-build-ppt', 'disabled'),
        Input('wz-build-ppt', 'n_clicks'),
        State('wz-event-path', 'value'),
        prevent_initial_call=True,
    )
    def build_ppt(_, event_path):
        # Imported lazily: callbacks.py imports this module.
        from app.callbacks import _ppt_thread
        r = state.batch_result or {}
        outputs = r.get('outputs') or []
        if not outputs or state.ppt_running:
            raise PreventUpdate
        template = load_settings().get('ppt_template') or DEFAULT_PPT_TEMPLATE_PATH
        stem     = os.path.splitext(os.path.basename(event_path or 'Charts'))[0]
        out_path = os.path.join(r['out_folder'], f"{stem}_Charts.pptx")
        state.ppt_running = True
        state.ppt_result  = None
        state.ppt_log_lines.clear()
        threading.Thread(
            target=_ppt_thread,
            args=(state, r['out_folder'], template, out_path, True, 96),
            kwargs={'images': [os.path.basename(p) for p in outputs]},
            daemon=True,
        ).start()
        return html.Small("⏳ Building PowerPoint…"), False, True

    @app.callback(
        Output('wz-ppt-status', 'children', allow_duplicate=True),
        Output('wz-ppt-interval', 'disabled', allow_duplicate=True),
        Output('wz-build-ppt', 'disabled', allow_duplicate=True),
        Input('wz-ppt-interval', 'n_intervals'),
        prevent_initial_call=True,
    )
    def poll_ppt(_):
        if state.ppt_running:
            raise PreventUpdate
        res = state.ppt_result or {}
        if res.get('success'):
            return (html.Div([html.Small(f"✓ Saved {res['path']}  "),
                              html.A(dbc.Button("⬇ Download PPTX", color='link', size='sm'),
                                     href='/api/wizard/pptx', download=True)]),
                    True, False)
        return (html.Small("✗ PowerPoint build failed — see the PPT Builder log in Advanced.",
                           className="text-danger"), True, False)

    # ── Download routes ──────────────────────────────────────────────────────
    server = app.server

    @server.route('/api/wizard/zip')
    def wizard_zip():
        r = state.batch_result or {}
        outputs = [p for p in r.get('outputs') or [] if os.path.isfile(p)]
        if not outputs:
            return "No images from the last run.", 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:   # PNGs are already compressed
            for p in outputs:
                zf.write(p, os.path.basename(p))
        buf.seek(0)
        name = os.path.basename(os.path.normpath(r['out_folder'])) or 'charts'
        return send_file(buf, mimetype='application/zip', as_attachment=True,
                         download_name=f"{name}.zip")

    @server.route('/api/wizard/pptx')
    def wizard_pptx():
        path = (state.ppt_result or {}).get('path')
        if not path or not os.path.isfile(path):
            return "No PowerPoint built yet.", 404
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
