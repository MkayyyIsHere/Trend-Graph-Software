"""1_app/results.py — 🔍 Results: browse every chart of the last run.

Images appear while a Quick Run is still drawing (the batch thread appends
to state.results as each PNG is saved). Step through them with ◀ ▶, the
arrow keys or the thumbnail strip, and narrow the set by data file or chart.

"Interactive" redraws the current chart as a zoomable Plotly figure with the
run's exact overrides (time window, Y limits, units) — see
backend.batch_worker.build_run_figure. Images loaded from a folder can be
viewed but not redrawn (there is no run context for them).
"""
import io
import os
from urllib.parse import quote

from dash import Input, Output, State, ALL, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from flask import request as flask_request, send_file

from backend.batch_worker import build_run_figure
from backend.config import GanttConfigManager
from backend.formats import ChartSkipped, DataFileError
from backend.processors import EventDataProcessor

_ALL     = '__all__'
_IMG_EXT = ('.png', '.jpg', '.jpeg')
_THUMB_W = 240


# ── Layout ───────────────────────────────────────────────────────────────────

def results_tab(log_card):
    """The Results tab; *log_card* is the batch log panel (built in layout.py)."""
    toolbar = dbc.Row([
        dbc.Col(dbc.Select(id='rs-filter-data', size='sm', value=_ALL,
                           options=[{'label': 'All data files', 'value': _ALL}]), lg=3),
        dbc.Col(dbc.Select(id='rs-filter-chart', size='sm', value=_ALL,
                           options=[{'label': 'All charts', 'value': _ALL}]), lg=2),
        dbc.Col(html.Div([
            dbc.Button("◀", id='rs-prev', color='secondary', size='sm', className='me-1',
                       title="Previous (← key)"),
            html.Span("0 / 0", id='rs-counter', className="small mx-2",
                      style={'minWidth': '64px', 'textAlign': 'center'}),
            dbc.Button("▶", id='rs-next', color='secondary', size='sm', title="Next (→ key)"),
        ], className="d-flex align-items-center"), width='auto'),
        dbc.Col(dbc.Switch(id='rs-interactive', label="Interactive", value=False,
                           className="mb-0 small"), width='auto',
                className="d-flex align-items-center"),
        dbc.Col(html.Div([
            html.Small(id='rs-source', className="text-muted me-2"),
            dbc.Button("📂 Open a folder of images…", id='rs-open-folder', color='link',
                       size='sm', className="p-0"),
        ], className="d-flex align-items-center justify-content-end"), className="ms-auto"),
    ], className="g-2 align-items-center mb-2")

    stage = html.Div(className="rs-stage", children=[
        html.Img(id='rs-img', style={'display': 'none'}),
        html.Div(id='rs-graph-wrap', style={'display': 'none', 'width': '100%', 'height': '100%'},
                 children=dcc.Loading(dcc.Graph(
                     id='rs-graph', responsive=True,
                     style={'width': '100%', 'height': '100%'},
                     config={'displayModeBar': True, 'scrollZoom': True,
                             'toImageButtonOptions': {'format': 'png', 'scale': 1}}),
                     parent_style={'width': '100%', 'height': '100%'})),
        html.Div(id='rs-empty', className="text-muted text-center p-4", children=[
            html.Div("No results yet.", className="fs-5 mb-1"),
            html.Div("Run Quick Run — charts appear here as they are drawn."),
        ]),
    ])

    return dbc.Tab(label="🔍 Results", tab_id="tab-results", children=[
        dbc.Container(fluid=True, style={'maxWidth': '1600px'}, children=[
            toolbar,
            stage,
            html.Div(id='rs-caption', className="small text-muted mt-1"),
            html.Div(id='rs-strip', className="rs-strip mb-2"),
            log_card,
            dcc.Store(id='rs-selected'),        # path of the image on show
            dcc.Store(id='rs-version'),         # changes when the result set changes
            dcc.Store(id='rs-folder'),          # folder picked via "Open a folder…"
            dcc.Store(id='rs-keys'),            # sink for the keyboard listener
            dcc.Interval(id='rs-interval', interval=1000, disabled=True),
        ]),
    ])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _img_url(path, thumb=False):
    try:
        v = int(os.path.getmtime(path))
    except OSError:
        v = 0
    return f"/api/results/img?path={quote(path)}&v={v}" + ("&thumb=1" if thumb else "")


def _filtered(results, f_data, f_chart):
    return [e for e in results
            if (f_data in (None, _ALL) or e['data_file'] == f_data)
            and (f_chart in (None, _ALL) or e['chart'] == f_chart)]


def _unique(values):
    return list(dict.fromkeys(values))


# ── Callbacks ────────────────────────────────────────────────────────────────

def register_results_callbacks(app, state):
    tasks_cache = {}      # event file path → (mtime, tasks)
    thumb_cache = {}      # (path, mtime) → PNG bytes

    def _snapshot():
        with state.results_lock:
            return list(state.results)

    def _tasks(event_file):
        mtime = os.path.getmtime(event_file)
        hit = tasks_cache.get(event_file)
        if hit and hit[0] == mtime:
            return hit[1]
        proc = EventDataProcessor()
        if not proc.load_csv(event_file):
            raise ValueError(f"the schedule could not be read: {proc.error}")
        tasks_cache[event_file] = (mtime, proc.get_tasks())
        return tasks_cache[event_file][1]

    # Poll only while the tab is open.
    @app.callback(Output('rs-interval', 'disabled'), Input('main-tabs', 'active_tab'))
    def poll_when_visible(tab):
        return tab != 'tab-results'

    # ← / → keys click ◀ / ▶ (ignored while typing in an input).
    app.clientside_callback(
        """
        function(id) {
            if (window._rsKeys) return window.dash_clientside.no_update;
            window._rsKeys = true;
            document.addEventListener('keydown', function(e) {
                var t = e.target.tagName;
                if (t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA') return;
                var tab = document.querySelector('#main-tabs .nav-link.active');
                if (!tab || tab.textContent.indexOf('Results') < 0) return;
                var btn = e.key === 'ArrowLeft' ? 'rs-prev' : e.key === 'ArrowRight' ? 'rs-next' : null;
                if (btn) { document.getElementById(btn).click(); e.preventDefault(); }
            });
            return '';
        }
        """,
        Output('rs-keys', 'data'),
        Input('rs-keys', 'id'),
    )

    # ── Result set changed → filters, source label, interactive availability
    @app.callback(
        Output('rs-version', 'data'),
        Output('rs-filter-data', 'options'),
        Output('rs-filter-chart', 'options'),
        Output('rs-source', 'children'),
        Output('rs-interactive', 'disabled'),
        Input('rs-interval', 'n_intervals'),
        Input('main-tabs', 'active_tab'),
        State('rs-version', 'data'),
    )
    def refresh(_, tab, version):
        if tab != 'tab-results':
            raise PreventUpdate
        results = _snapshot()
        run_ctx = state.results_ctx
        new = f"{len(results)}|{id(run_ctx)}|{results[0]['path'] if results else ''}|{state.batch_running}"
        if new == version:
            raise PreventUpdate
        data_opts  = [{'label': 'All data files', 'value': _ALL}] + [
            {'label': d, 'value': d} for d in _unique(e['data_file'] for e in results)]
        chart_opts = [{'label': 'All charts', 'value': _ALL}] + [
            {'label': c, 'value': c} for c in _unique(e['chart'] for e in results)]
        if state.batch_running:
            source = f"Drawing… {len(results)} image(s) so far"
        elif not results:
            source = ""
        else:
            folder = os.path.basename(os.path.dirname(results[0]['path']))
            source = (f"{len(results)} image(s) from folder “{folder}”"
                      if not results[0].get('cfg_path') else
                      f"Last run — {len(results)} image(s) in “{folder}”")
        no_ctx = run_ctx is None or not results or not results[0].get('cfg_path')
        return new, data_opts, chart_opts, source, no_ctx

    # ── Thumbnail strip (re-rendered only when the set or filters change) ───
    @app.callback(
        Output('rs-strip', 'children'),
        Input('rs-version', 'data'),
        Input('rs-filter-data', 'value'),
        Input('rs-filter-chart', 'value'),
        State('rs-selected', 'data'),
    )
    def render_strip(_, f_data, f_chart, selected):
        shown = _filtered(_snapshot(), f_data, f_chart)
        return [html.Div([html.Img(src=_img_url(e['path'], thumb=True)),
                          html.Small(e['chart']),
                          html.Small(e['data_file'], className="text-muted")],
                         id={'type': 'rs-thumb', 'key': e['path']}, n_clicks=0,
                         className="rs-thumb" + (" active" if e['path'] == selected else ""),
                         title=os.path.basename(e['path']))
                for e in shown]

    @app.callback(
        Output({'type': 'rs-thumb', 'key': ALL}, 'className'),
        Input('rs-selected', 'data'),
        State({'type': 'rs-thumb', 'key': ALL}, 'id'),
    )
    def highlight(selected, ids):
        return ["rs-thumb" + (" active" if i['key'] == selected else "") for i in ids]

    # Scroll the active thumbnail into view.
    app.clientside_callback(
        """
        function(sel) {
            setTimeout(function() {
                var el = document.querySelector('.rs-thumb.active');
                if (el) el.scrollIntoView({block: 'nearest', inline: 'center'});
            }, 50);
            return window.dash_clientside.no_update;
        }
        """,
        Output('rs-strip', 'data-scroll'),
        Input('rs-selected', 'data'),
    )

    # ── Selection: thumbnail click, ◀ ▶, or the set/filters changing ───────
    @app.callback(
        Output('rs-selected', 'data'),
        Input({'type': 'rs-thumb', 'key': ALL}, 'n_clicks'),
        Input('rs-prev', 'n_clicks'),
        Input('rs-next', 'n_clicks'),
        Input('rs-version', 'data'),
        Input('rs-filter-data', 'value'),
        Input('rs-filter-chart', 'value'),
        State('rs-selected', 'data'),
    )
    def select(_clicks, _p, _n, _v, f_data, f_chart, selected):
        shown = [e['path'] for e in _filtered(_snapshot(), f_data, f_chart)]
        if not shown:
            return None
        # A set change re-renders the strip in the same update, so new
        # thumbnails (n_clicks 0) can appear among the triggers — only a real
        # click counts.
        trig    = ctx.triggered_id
        clicked = [t for t in ctx.triggered if t['prop_id'].startswith('{') and t['value']]
        if isinstance(trig, dict) and clicked and len(ctx.triggered) == 1:
            return trig['key']
        if isinstance(trig, dict):
            trig = next((t['prop_id'].split('.')[0] for t in ctx.triggered
                         if not t['prop_id'].startswith('{')), None)
        pos = shown.index(selected) if selected in shown else None
        if trig in ('rs-prev', 'rs-next'):
            if pos is None:
                return shown[0]
            pos = max(0, min(len(shown) - 1, pos + (1 if trig == 'rs-next' else -1)))
            return shown[pos]
        return selected if pos is not None else shown[0]

    # ── Show the selected image (or its interactive redraw) ──────────────────
    @app.callback(
        Output('rs-img', 'src'),
        Output('rs-img', 'style'),
        Output('rs-graph-wrap', 'style'),
        Output('rs-graph', 'figure'),
        Output('rs-empty', 'style'),
        Output('rs-caption', 'children'),
        Output('rs-counter', 'children'),
        Input('rs-selected', 'data'),
        Input('rs-interactive', 'value'),
        State('rs-filter-data', 'value'),
        State('rs-filter-chart', 'value'),
    )
    def show(selected, interactive, f_data, f_chart):
        results = _snapshot()
        shown   = _filtered(results, f_data, f_chart)
        entry   = next((e for e in shown if e['path'] == selected), None)
        hidden, block = {'display': 'none'}, {'display': 'block'}
        if entry is None:
            msg = block if not results else {'display': 'none'}
            return "", hidden, hidden, no_update, msg, "", f"0 / {len(shown)}"
        counter = f"{shown.index(entry) + 1} / {len(shown)}"
        caption = [html.B(entry['chart']), f" · {entry['data_file']} · ",
                   html.Span(os.path.basename(entry['path']), style={'fontFamily': 'monospace'})]
        run_ctx = state.results_ctx
        if interactive and run_ctx and entry.get('cfg_path'):
            try:
                fig = build_run_figure(
                    entry['cfg_path'], entry['data_path'], run_ctx,
                    _tasks(run_ctx['event_file']), GanttConfigManager(run_ctx.get('gantt_path')),
                    sized=False)
            except (ChartSkipped, DataFileError, ValueError, OSError) as e:
                caption += [html.Span(f"  — cannot redraw: {e}", className="text-danger")]
                return (_img_url(entry['path']), {}, hidden, no_update, hidden,
                        caption, counter)
            return ("", hidden, {'width': '100%', 'height': '100%'}, fig, hidden,
                    caption, counter)
        return _img_url(entry['path']), {}, hidden, no_update, hidden, caption, counter

    # ── Open a folder of existing images (view only) ─────────────────────────
    app.clientside_callback(
        """
        function(n) {
            if (!n) return window.dash_clientside.no_update;
            return fetch('/api/pick-folder?title=Select%20Image%20Folder').then(r => r.json())
                .then(d => d.path || window.dash_clientside.no_update);
        }
        """,
        Output('rs-folder', 'data'),
        Input('rs-open-folder', 'n_clicks'),
        prevent_initial_call=True,
    )

    @app.callback(
        Output('rs-source', 'children', allow_duplicate=True),
        Input('rs-folder', 'data'),
        prevent_initial_call=True,
    )
    def open_folder(folder):
        if not folder or not os.path.isdir(folder):
            raise PreventUpdate
        if state.batch_running:
            return "A run is in progress — wait for it to finish."
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(_IMG_EXT))
        entries = []
        for f in files:
            stem = os.path.splitext(f)[0]
            # Batch names are "<data file>__<chart>"; fall back to the file name.
            data, _, chart = stem.rpartition('__')
            entries.append({'path': os.path.join(folder, f), 'data_file': data or stem,
                            'chart': chart or stem, 'cfg_path': None, 'data_path': None,
                            'order': len(entries)})
        with state.results_lock:
            state.results     = entries
            state.results_ctx = None
        return no_update if entries else "No images in that folder."

    # ── Image route (only paths in the current result set are served) ────────
    @app.server.route('/api/results/img')
    def results_img():
        path = flask_request.args.get('path', '')
        if not any(e['path'] == path for e in _snapshot()) or not os.path.isfile(path):
            return "Not found", 404
        if not flask_request.args.get('thumb'):
            return send_file(path, max_age=3600)
        key = (path, os.path.getmtime(path))
        data = thumb_cache.get(key)
        if data is None:
            from PIL import Image
            with Image.open(path) as im:
                im.thumbnail((_THUMB_W, _THUMB_W))
                buf = io.BytesIO()
                im.convert('RGB').save(buf, 'PNG', optimize=True)
            data = thumb_cache[key] = buf.getvalue()
        return send_file(io.BytesIO(data), mimetype='image/png', max_age=3600)
