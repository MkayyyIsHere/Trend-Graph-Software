"""1_app/callbacks.py — Shared callbacks (logs, PowerPoint tab) + registration of the per-tab modules."""
import os
import re
import threading
import traceback

from dash import Input, Output, State, ALL, ctx, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from utils.constants import DEFAULT_PPT_TEMPLATE_PATH, load_settings, save_settings
from backend.ppt_builder import PPTBuilder

try:
    from pptx import Presentation  # noqa: F401
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

from app.config_manager_callbacks import register_config_manager_callbacks
from app.results import register_results_callbacks
from app.wizard import register_wizard_callbacks

# ── Helpers ──────────────────────────────────────────────────────────────────

_CLASS_TO_COLOR = {
    'log-info':    '#a6e3a1',
    'log-warning': '#f9e2af',
    'log-error':   '#f38ba8',
    'log-debug':   '#89b4fa',
    'log-default': '#cdd6f4',
}

def _log_spans(lines, classifier):
    """Convert a list of log strings into colored html.Span elements."""
    spans = []
    for line in lines[-500:]:
        cls = classifier(line)
        color = _CLASS_TO_COLOR.get(cls, '#cdd6f4')
        spans.append(html.Span(line + '\n', style={'color': color}))
    return spans


def _batch_log_class(line):
    if '✓' in line:                                                  return 'log-info'
    if '↷' in line:                                                  return 'log-warning'
    if '✗' in line or 'ERROR' in line or 'FAILED' in line or 'ABORTED' in line: return 'log-error'
    if 'WARNING' in line or 'SKIPPED' in line or '⚠' in line:       return 'log-warning'
    if '=' * 10 in line or 'BATCH' in line:                          return 'log-debug'
    return 'log-default'


def _ppt_log_class(line):
    if '[INFO]' in line or '✓' in line:    return 'log-info'
    if '[ERROR]' in line or '✗' in line:   return 'log-error'
    if '[WARNING]' in line:                return 'log-warning'
    if '[DEBUG]' in line:                  return 'log-debug'
    return 'log-default'


# ── PPT thread helper ────────────────────────────────────────────────────────

class _RelayLogger:
    """Lightweight logger that prefixes and appends to a list."""
    def __init__(self, cb):
        self._cb = cb
    def info(self,    m): self._cb(f"[INFO]    {m}")
    def warning(self, m): self._cb(f"[WARNING] {m}")
    def error(self,   m): self._cb(f"[ERROR]   {m}")
    def debug(self,   m): self._cb(f"[DEBUG]   {m}")


def _ppt_thread(state, img_folder, template, out_path, auto_resize, slide_dpi, images=None):
    plog = state.ppt_log_lines.append

    def _progress(cur, total, fname):
        plog(f"  Slide {cur}/{total} — {fname}")

    builder = PPTBuilder(logger=_RelayLogger(plog))
    try:
        result = builder.build(
            img_folder, template, out_path,
            auto_resize_slide=auto_resize,
            slide_dpi=slide_dpi,
            progress_callback=_progress,
            images=images,
        )
        if result:
            state.last_pptx_path = result
            plog(f"\n✓ PPTX saved: {result}")
            state.ppt_result = {'success': True, 'path': result}
        else:
            plog("\n✗ Build failed — see errors above.")
            state.ppt_result = {'success': False}
    except PPTBuilder.NoPicturePlaceholderError as e:
        plog(f"\n✗ {e}")
        state.ppt_result = {'success': False}
    except Exception as e:
        plog(f"\n✗ Unexpected error: {e}\n{traceback.format_exc()}")
        state.ppt_result = {'success': False}
    finally:
        state.ppt_running = False


def _image_list(order):
    """Slide checklist rows: [☑ n. name  ▲ ▼]."""
    if not order:
        return html.P("No images — run Quick Run first, or pick a folder.",
                      className="text-muted small m-2")
    rows = []
    for i, row in enumerate(order):
        rows.append(html.Div([
            dbc.Checkbox(id={'type': 'ppt-on', 'i': i}, value=row['on'], className="me-2"),
            html.Span(f"{i + 1}.", className="small text-muted me-2", style={'minWidth': '28px'}),
            html.Span(row['name'], className="small flex-grow-1",
                      style={'fontFamily': 'monospace', 'wordBreak': 'break-all',
                             'opacity': 1 if row['on'] else 0.5}),
            dbc.Button("▲", id={'type': 'ppt-up', 'i': i}, size='sm', color='light',
                       className="py-0 px-1 me-1 border", disabled=i == 0),
            dbc.Button("▼", id={'type': 'ppt-down', 'i': i}, size='sm', color='light',
                       className="py-0 px-1 border", disabled=i == len(order) - 1),
        ], className="d-flex align-items-center px-2 py-1 border-bottom"))
    return rows


def _default_pptx_name():
    stem = os.path.splitext(os.path.basename(load_settings().get('wz_event_path') or 'Charts'))[0]
    return f"{stem}_Charts.pptx"


# ── Main registration function ───────────────────────────────────────────────

def register_callbacks(app, state, temp_dir: str):
    """Register all server-side and clientside callbacks on *1_app*."""

    # ── Browse buttons → Flask picker endpoints (clientside) ─────────────────
    for btn_id, inp_id, url in [
        ('btn-browse-ppt-tmpl',       'ppt-template',      '/api/pick-file?kind=pptx&save=false'),
        ('btn-browse-ppt-img',        'ppt-img-folder',    '/api/pick-folder?title=Select%20Image%20Folder'),
        ('btn-browse-ppt-out-folder', 'ppt-output-folder', '/api/pick-folder?title=Select%20Output%20Folder'),
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

    # ── Log panels: auto-scroll, copy, show/hide, clear ──────────────────────
    for log_id in ('batch-log-output', 'ppt-log-output'):
        app.clientside_callback(
            f"""
            function(children) {{
                var el = document.getElementById('{log_id}');
                if (el) {{ el.scrollTop = el.scrollHeight; }}
                return window.dash_clientside.no_update;
            }}
            """,
            Output(log_id, 'data-scroll'),
            Input(log_id, 'children'),
        )

    for btn_id, src_id, ta_id in [
        ('btn-copy-batch-log', 'batch-log-output', 'batch-log-text-hidden'),
        ('btn-copy-ppt-log',   'ppt-log-output',   'ppt-log-text-hidden'),
    ]:
        app.clientside_callback(
            f"""
            function(n) {{
                if (!n) return '';
                var el = document.getElementById('{src_id}');
                if (!el) return '';
                var text = el.innerText || el.textContent || '';
                navigator.clipboard.writeText(text).catch(function() {{
                    var ta = document.getElementById('{ta_id}');
                    if (ta) {{ ta.value = text; ta.select(); document.execCommand('copy'); }}
                }});
                return '';
            }}
            """,
            Output(ta_id, 'value'),
            Input(btn_id, 'n_clicks'),
            prevent_initial_call=True,
        )

    for toggle_id, collapse_id in [
        ('btn-toggle-batch-log', 'batch-log-collapse'),
        ('btn-toggle-ppt-log',   'ppt-log-collapse'),
    ]:
        @app.callback(
            Output(collapse_id, 'is_open'),
            Output(toggle_id, 'children'),
            Input(toggle_id, 'n_clicks'),
            State(collapse_id, 'is_open'),
            prevent_initial_call=True,
        )
        def _toggle(_, is_open):
            new = not is_open
            return new, "Hide Log" if new else "Show Log"

    @app.callback(
        Output('batch-log-output', 'children', allow_duplicate=True),
        Input('btn-clear-batch-log', 'n_clicks'),
        prevent_initial_call=True,
    )
    def clear_batch_log(_):
        state.batch_log.clear()
        return []

    @app.callback(
        Output('ppt-log-output', 'children', allow_duplicate=True),
        Input('btn-clear-ppt-log', 'n_clicks'),
        prevent_initial_call=True,
    )
    def clear_ppt_log(_):
        state.ppt_log_lines.clear()
        return []

    # Run log (Results tab) — refreshed while the panel is open.
    @app.callback(
        Output('batch-log-output', 'children'),
        Input('rs-interval', 'n_intervals'),
        Input('batch-log-collapse', 'is_open'),
    )
    def update_batch_log(_, is_open):
        if not is_open:
            raise PreventUpdate
        return _log_spans(list(state.batch_log), _batch_log_class)

    # ── PowerPoint tab ────────────────────────────────────────────────────────
    @app.callback(
        Output('ppt-more', 'is_open'),
        Input('ppt-more-toggle', 'n_clicks'),
        State('ppt-more', 'is_open'),
        prevent_initial_call=True,
    )
    def toggle_more(_, is_open):
        return not is_open

    @app.callback(
        Output('ppt-template', 'value', allow_duplicate=True),
        Input('ppt-template-default', 'n_clicks'),
        prevent_initial_call=True,
    )
    def ppt_template_default(_):
        return ''

    # Same remembered template as Quick Run (settings 'ppt_template').
    @app.callback(
        Output('ppt-template-info', 'children'),
        Input('ppt-template', 'value'),
    )
    def ppt_template_info(path):
        path = (path or '').strip().strip('"')
        if not path:
            save_settings(ppt_template='')
            return "Using the built-in template."
        if not path.lower().endswith('.pptx') or not os.path.isfile(path):
            return html.Span("✗ Not found — the built-in template will be used.",
                             className="text-danger")
        save_settings(ppt_template=path)
        return f"✓ {os.path.basename(path)}"

    # Source → slide list (refreshed whenever the tab is opened).
    @app.callback(
        Output('ppt-order', 'data'),
        Output('ppt-folder', 'data'),
        Output('ppt-folder-row', 'style'),
        Output('ppt-filename', 'value'),
        Input('ppt-source', 'value'),
        Input('ppt-img-folder', 'value'),
        Input('main-tabs', 'active_tab'),
        State('ppt-filename', 'value'),
    )
    def load_slides(source, folder, tab, filename):
        if ctx.triggered_id == 'main-tabs' and tab != 'tab-ppt':
            raise PreventUpdate
        name = filename or _default_pptx_name()
        if source == 'folder':
            row = {'display': 'block'}
            if not folder or not os.path.isdir(folder):
                return [], '', row, name
            names = PPTBuilder().collect_images(folder)
            return [{'name': n, 'on': True} for n in names], folder, row, name
        with state.results_lock:
            paths = [e['path'] for e in state.results if os.path.isfile(e['path'])]
        if not paths:
            return [], '', {'display': 'none'}, name
        return ([{'name': os.path.basename(p), 'on': True} for p in paths],
                os.path.dirname(paths[0]), {'display': 'none'}, name)

    @app.callback(
        Output('ppt-image-list', 'children'),
        Output('ppt-count', 'children'),
        Input('ppt-order', 'data'),
    )
    def render_slides(order):
        n_on = sum(r['on'] for r in order or [])
        return _image_list(order or []), f"{n_on} of {len(order or [])} selected"

    # Reorder / select all / none. Checkbox states are read here (not stored on
    # every click) so re-rendering the list never loops back into this callback.
    @app.callback(
        Output('ppt-order', 'data', allow_duplicate=True),
        Input({'type': 'ppt-up', 'i': ALL}, 'n_clicks'),
        Input({'type': 'ppt-down', 'i': ALL}, 'n_clicks'),
        Input('ppt-all', 'n_clicks'),
        Input('ppt-none', 'n_clicks'),
        State({'type': 'ppt-on', 'i': ALL}, 'value'),
        State('ppt-order', 'data'),
        prevent_initial_call=True,
    )
    def edit_slides(_up, _down, _all, _none, ons, order):
        if not order or not ctx.triggered[0]['value']:
            raise PreventUpdate
        order = [{'name': r['name'], 'on': bool(on)} for r, on in zip(order, ons)]
        trig = ctx.triggered_id
        if trig in ('ppt-all', 'ppt-none'):
            return [{'name': r['name'], 'on': trig == 'ppt-all'} for r in order]
        i, j = trig['i'], trig['i'] + (-1 if trig['type'] == 'ppt-up' else 1)
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
        return order

    @app.callback(
        Output('ppt-out-info', 'children'),
        Input('ppt-folder', 'data'),
        Input('ppt-output-folder', 'value'),
        Input('ppt-filename', 'value'),
    )
    def out_info(img_folder, out_folder, filename):
        folder = (out_folder or '').strip() or img_folder
        if not folder:
            return ""
        return f"Saved to {os.path.join(folder, filename or '')}"

    @app.callback(
        Output('ppt-build-status', 'children'),
        Output('btn-ppt-build', 'disabled'),
        Input('btn-ppt-build', 'n_clicks'),
        State('ppt-order', 'data'),
        State({'type': 'ppt-on', 'i': ALL}, 'value'),
        State('ppt-folder', 'data'),
        State('ppt-template', 'value'),
        State('ppt-output-folder', 'value'),
        State('ppt-filename', 'value'),
        State('ppt-dpi', 'value'),
        State('ppt-auto-resize', 'value'),
        prevent_initial_call=True,
    )
    def ppt_build(_, order, ons, img_folder, template, out_folder, filename, dpi_val, auto_resize):
        if not _PPTX_AVAILABLE:
            return dbc.Alert("python-pptx not installed.", color="danger"), False
        if state.ppt_running:
            raise PreventUpdate
        images = [r['name'] for r, on in zip(order or [], ons) if on]
        if not images:
            return dbc.Alert("Select at least one image.", color="warning", className="py-1"), False
        out_folder = (out_folder or '').strip() or img_folder
        if not os.path.isdir(out_folder or ''):
            return dbc.Alert("The output folder does not exist.", color="warning",
                             className="py-1"), False
        template = (template or '').strip().strip('"')
        if not os.path.isfile(template):
            template = DEFAULT_PPT_TEMPLATE_PATH

        safe_name = re.sub(r'[<>:"/\\|?*]', '_', (filename or '').strip()) or _default_pptx_name()
        if not safe_name.lower().endswith('.pptx'):
            safe_name += '.pptx'
        out_path = os.path.join(out_folder, safe_name)
        try:
            slide_dpi = int(dpi_val) if dpi_val else 96
        except (TypeError, ValueError):
            slide_dpi = 96

        state.ppt_running = True
        state.ppt_result  = None
        state.ppt_log_lines.clear()
        threading.Thread(
            target=_ppt_thread,
            args=(state, img_folder, template, out_path, bool(auto_resize), slide_dpi),
            kwargs={'images': images},
            daemon=True,
        ).start()
        return html.Small(f"⏳ Building {len(images)} slide(s) with {os.path.basename(template)}…"), True

    @app.callback(
        Output('ppt-log-output', 'children'),
        Output('btn-ppt-build', 'disabled', allow_duplicate=True),
        Output('ppt-build-status', 'children', allow_duplicate=True),
        Output('store-ppt-result', 'data'),
        Input('interval-ppt', 'n_intervals'),
        State('store-ppt-result', 'data'),
        prevent_initial_call=True,
    )
    def poll_ppt(_, shown):
        result = state.ppt_result
        key = None if result is None else (result.get('success'), result.get('path'))
        if state.ppt_running or key == (tuple(shown) if shown else None):
            spans = _log_spans(list(state.ppt_log_lines), _ppt_log_class)
            return spans, state.ppt_running, no_update, no_update
        spans = _log_spans(list(state.ppt_log_lines), _ppt_log_class)
        if result.get('success'):
            status = html.Div([
                html.Span(f"✓ Saved {result['path']}  ", className="text-success"),
                html.A(dbc.Button("⬇ Download", color='link', size='sm', className="p-0"),
                       href='/api/wizard/pptx', download=True),
            ])
        else:
            status = html.Span("✗ Build failed — open the log below.", className="text-danger")
        return spans, False, status, list(key)

    # ── Per-tab modules ───────────────────────────────────────────────────────
    register_config_manager_callbacks(app, state)
    register_wizard_callbacks(app, state)
    register_results_callbacks(app, state)

    # ── Auto-dismiss status messages ──────────────────────────────────────────
    # When a status message appears, clear it after 4 seconds by writing ""
    # back through a proper Dash Output — this keeps Dash's virtual DOM in
    # sync so repeated saves always re-trigger the indicator correctly.
    for _sid in ('cfgmgr-status', 'cfg-save-status'):
        app.clientside_callback(
            f"""
            function(children) {{
                if (children === null || children === undefined || children === '') {{
                    return window.dash_clientside.no_update;
                }}
                return new Promise(function(resolve) {{
                    setTimeout(function() {{ resolve(''); }}, 4000);
                }});
            }}
            """,
            Output(_sid, 'children', allow_duplicate=True),
            Input(_sid, 'children'),
            prevent_initial_call=True,
        )
