"""1_app/callbacks.py — All Dash @1_app.callback and clientside_callback registrations."""
import base64
import os
import re
import threading
import traceback

import pandas as pd
import plotly.graph_objects as go

from dash import Input, Output, State, dash_table, ctx, html, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from utils.constants import (DEFAULT_DPI, DEFAULT_FIGURE_SIZE, RESOLUTION_PRESETS,
                             RESERVED_CONFIG_FILENAMES, load_settings)
from backend.processors import EventDataProcessor
from backend.formats import ChartSkipped, DataFileError, load_chart_data
from backend.units import AUTO, apply_display_unit
from backend.plotly_preview import build_plotly_figure
from backend.batch_worker import render_png, run_batch as _run_batch_worker
from backend.ppt_builder import PPTBuilder

try:
    from pptx import Presentation  # noqa: F401
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

from app.config_manager_callbacks import register_config_manager_callbacks
from app.batch_profile_callbacks import register_batch_profile_callbacks
from app.wizard import register_wizard_callbacks
from backend.batch_profile import BatchProfileManager

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


def _main_log_class(line):
    if '] WARNING:' in line:    return 'log-warning'
    if '] ERROR:' in line or '] CRITICAL:' in line: return 'log-error'
    if '] DEBUG:' in line:      return 'log-debug'
    if '] INFO:' in line:       return 'log-info'
    return 'log-default'


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


def _find_in_folder(filename, current_path):
    """Try to locate a file to extract its parent folder path."""
    bases = ([os.path.dirname(current_path)] if current_path else []) + [os.getcwd()]
    for base in bases:
        candidate = os.path.join(base, filename)
        if os.path.isfile(candidate):
            return os.path.dirname(os.path.abspath(candidate))
    return None


def _save_upload(contents, filename, temp_dir):
    """Decode a dcc.Upload payload, save to temp_dir, return the path."""
    if not contents or not filename:
        raise PreventUpdate
    _, content_string = contents.split(',', 1)
    decoded  = base64.b64decode(content_string)
    out_path = os.path.join(temp_dir, filename)
    with open(out_path, 'wb') as f:
        f.write(decoded)
    return out_path


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


# ── Main registration function ───────────────────────────────────────────────

def register_callbacks(app, state, temp_dir: str):
    """Register all server-side and clientside callbacks on *1_app*."""

    # ── File Browse buttons → Flask file-picker endpoint (clientside) ────────
    _file_browse = [
        ('btn-browse-gantt',    'gantt-config-path',  'json',   False),
        ('btn-browse-event',    'event-file-path',    'events', False),
        ('btn-browse-config',   'plot-config-path',   'json',   False),
        ('btn-browse-series',   'series-file-path',   'data',   False),
        ('btn-browse-export',   'export-output-path', 'export', True),
        ('btn-browse-ppt-tmpl', 'ppt-template',       'pptx',   False),
    ]
    for btn_id, inp_id, kind, save in _file_browse:
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

    # ── Folder Browse buttons → Flask folder-picker endpoint (clientside) ────
    _folder_browse = [
        ('btn-browse-batch-config',   'batch-config-folder',  'Select Config Folder'),
        ('btn-browse-batch-data',     'batch-data-folder',    'Select Data Folder'),
        ('btn-browse-batch-output',   'batch-output-folder',  'Select Output Folder'),
        ('btn-browse-ppt-img',        'ppt-img-folder',       'Select Image Folder'),
        ('btn-browse-ppt-out-folder', 'ppt-output-folder',    'Select Output Folder'),
        ('btn-cfgmgr-browse',         'cfgmgr-folder-path',   'Select Config Folder'),
    ]
    for btn_id, inp_id, title in _folder_browse:
        app.clientside_callback(
            f"""
            function(n) {{
                if (!n) return window.dash_clientside.no_update;
                return fetch('/api/pick-folder?title={title.replace(" ", "%20")}')
                    .then(r => r.json())
                    .then(d => d.path || window.dash_clientside.no_update);
            }}
            """,
            Output(inp_id, 'value', allow_duplicate=True),
            Input(btn_id, 'n_clicks'),
            prevent_initial_call=True,
        )

    # ── (Upload drop zones removed — all paths set via Browse buttons only) ──

    # ── Auto-scroll logs (clientside) ────────────────────────────────────────
    for log_id in ('log-output', 'batch-log-output', 'ppt-log-output'):
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

    # ── Copy log buttons (clientside) ────────────────────────────────────────
    _copy_map = [
        ('btn-copy-log',       'log-output',       'log-text-hidden'),
        ('btn-copy-batch-log', 'batch-log-output', 'batch-log-text-hidden'),
        ('btn-copy-ppt-log',   'ppt-log-output',   'ppt-log-text-hidden'),
    ]
    for btn_id, src_id, ta_id in _copy_map:
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

    # ── Log panel toggles (unified) ───────────────────────────────────────────
    for toggle_id, collapse_id in [
        ('btn-toggle-log',       'log-collapse'),
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

    # ── Log clear buttons ─────────────────────────────────────────────────────
    @app.callback(
        Output('log-output', 'children', allow_duplicate=True),
        Input('btn-clear-log', 'n_clicks'),
        prevent_initial_call=True,
    )
    def clear_main_log(_):
        state.log_lines.clear()
        return []

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

    # ── E-Stop batch ──────────────────────────────────────────────────────────
    @app.callback(
        Output('store-batch-result', 'data', allow_duplicate=True),
        Input('btn-estop', 'n_clicks'),
        prevent_initial_call=True,
    )
    def estop_batch(_):
        if state.batch_running:
            state.batch_stop_event.set()
            state.logger.warning("E-Stop requested — waiting for in-progress charts to finish…")
        return no_update

    # ── Auto-load Gantt config ────────────────────────────────────────────────
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
        if state.gantt_config.reload(path):
            gc = state.gantt_config.get_gantt_config()
            state.logger.info(f"Gantt config loaded: {path}")
            return dbc.Alert(f"✓ Loaded: {os.path.basename(path)}  "
                             f"(bar_alpha={gc.get('bar_alpha', '?')})",
                             color="success", className="py-1"), True
        return dbc.Alert("Failed to load gantt config — check JSON structure.",
                         color="danger", className="py-1"), False

    # ── Auto-load Plot config ─────────────────────────────────────────────────
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

        # Resolve aesthetics.json — look in the same folder as the chart config.
        # This covers the standard layout (aesthetics.json lives alongside chart JSONs).
        # Falls back to DEFAULT_AESTHETICS_PATH if not found there.
        from utils.constants import DEFAULT_AESTHETICS_PATH
        cfg_folder      = os.path.dirname(os.path.abspath(path))
        candidate       = os.path.join(cfg_folder, 'aesthetics.json')
        aesthetics_path = candidate if os.path.isfile(candidate) else DEFAULT_AESTHETICS_PATH

        # Update the aesthetics path on the shared config so reload() uses it.
        state.config.aesthetics_path = aesthetics_path

        if state.config.reload(path):
            sname = state.config.get_series_name()
            state.logger.info(f"Config loaded: {path}  |  Series: {sname}  "
                              f"|  aesthetics: {os.path.basename(aesthetics_path)}")
            return dbc.Alert(f"✓ {os.path.basename(path)}  — Series: {sname}",
                             color="success", className="py-1"), True
        return dbc.Alert("Failed to load config — check JSON structure.",
                         color="danger", className="py-1"), False

    # ── Preview buttons ───────────────────────────────────────────────────────
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
    def handle_previews(_, __, ___, series_path, event_path):
        trigger = ctx.triggered_id
        if trigger == 'btn-close-preview':
            return False, "", ""
        path  = series_path if trigger == 'btn-preview-series' else event_path
        title = "Series Data Preview" if trigger == 'btn-preview-series' else "Event / Task Preview"
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
                style_cell={'fontSize': '11px', 'padding': '4px 8px', 'fontFamily': 'monospace'},
                style_header={'fontWeight': 'bold', 'background': '#f0f0f0'},
                page_size=50,
            )
            return True, f"{title} ({len(df)} rows, {len(df.columns)} cols)", tbl
        except Exception as e:
            return True, title, dbc.Alert(f"Error: {e}", color="danger")

    # ── Clear generate-status immediately when Generate is clicked ────────────
    app.clientside_callback(
        """
        function(n) {
            if (!n) return window.dash_clientside.no_update;
            return '';
        }
        """,
        Output('generate-status', 'children', allow_duplicate=True),
        Input('btn-generate', 'n_clicks'),
        prevent_initial_call=True,
    )

    # ── Generate chart ────────────────────────────────────────────────────────
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
        _fail = (True, False, None, None)  # disabled, not ready, no summaries
        if not series_path or not os.path.isfile(series_path):
            return (dbc.Alert("Series data file not found.", color="warning"), *_fail)
        if not event_path or not os.path.isfile(event_path):
            return (dbc.Alert("Event CSV file not found.", color="warning"), *_fail)
        if not state.config.config:
            return (dbc.Alert("Load a plot config file first.", color="warning"), *_fail)

        state.logger.info("=" * 50)
        state.logger.info("Starting chart generation…")

        # Reload so a metric-based config starts from its style slots again.
        state.config.reload(state.config.config_path)
        try:
            all_data_points = load_chart_data(
                state.config, series_path, load_settings().get('wz_system', '3P4W'))
        except (ChartSkipped, DataFileError) as e:
            state.logger.error(f"Data load: {e}")
            return (dbc.Alert(f"Cannot draw this chart from that file: {e}", color="danger"), *_fail)
        # Same unit choice as the Quick Run table (auto = from limits / data peak)
        unit_choice = load_settings().get('wz_units', {}).get(
            os.path.basename(state.config.config_path or ''), AUTO)
        unit = apply_display_unit(state.config, all_data_points, unit_choice)
        series_summaries = []
        for sc, pts in zip(state.config.get_all_series_configs(), all_data_points):
            vals = [dp.value for dp in pts]
            series_summaries.append({
                'Series':    f"{sc.get('name')} ({sc.get('value_column', '')})",
                'Points':    len(pts),
                'Start':     str(pts[0].timestamp) if pts else '—',
                'End':       str(pts[-1].timestamp) if pts else '—',
                'Value Min': f"{min(vals):.4f} {unit or ''}".strip() if vals else '—',
                'Value Max': f"{max(vals):.4f} {unit or ''}".strip() if vals else '—',
            })

        event_proc = EventDataProcessor(logger=state.logger)
        if not event_proc.load_csv(event_path):
            return (dbc.Alert("Failed to load event CSV.", color="danger"), *_fail)
        tasks = event_proc.get_tasks()
        es    = event_proc.get_summary()
        state.logger.info(f"Events: {es['total_tasks']} tasks  IDs: {', '.join(es['test_ids'])}")

        cc       = state.config.get_chart_config()
        dpi      = cc.get('dpi', DEFAULT_DPI)
        fig_size = cc.get('figure_size', DEFAULT_FIGURE_SIZE)
        width_px = int(round(fig_size[0] * dpi))
        height_px= int(round(fig_size[1] * dpi))
        try:
            fig = build_plotly_figure(
                state.config, all_data_points, tasks, state.gantt_config,
                width=width_px, height=height_px,
            )
            # Store PNG bytes for any downstream consumers (e.g. PPT builder)
            state.last_png_bytes = render_png(fig, width_px, height_px)
        except Exception as e:
            state.logger.error(f"Chart generation failed: {e}")
            return (dbc.Alert("Chart generation failed — see log.", color="danger"), *_fail)
        state.last_all_data_points = all_data_points
        state.last_tasks           = tasks
        state.logger.info("Chart ready in memory")

        task_rows = [{'Test ID':     t.display_id,
                      'Description': t.description,
                      'Start':       t.start_time.strftime('%Y-%m-%d %H:%M'),
                      'End':         t.end_time.strftime('%Y-%m-%d %H:%M'),
                      'Norm':        '✓' if t.is_normalization else ''}
                     for t in tasks]
        res     = state.config.get_chart_config().get('resolution_px')
        res_str = f"{int(res[0])}×{int(res[1])} px" if res else ""
        return (
            dbc.Alert(f"✓ Chart ready!  {res_str}  — switch to Live Preview tab.", color="success"),
            False, True, series_summaries, task_rows,
        )

    # ── Export chart ──────────────────────────────────────────────────────────
    @app.callback(
        Output('generate-status', 'children', allow_duplicate=True),
        Input('btn-export', 'n_clicks'),
        State('export-output-path', 'value'),
        prevent_initial_call=True,
    )
    def export_chart(_, out_path):
        if state.last_png_bytes is None:
            return dbc.Alert("Generate a chart first.", color="warning")
        if not out_path:
            return dbc.Alert("Enter an export output path first (or click Browse).", color="warning")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            cc       = state.config.get_chart_config()
            dpi      = cc.get('dpi', DEFAULT_DPI)
            fig_size = cc.get('figure_size', DEFAULT_FIGURE_SIZE)
            width_px = int(round(fig_size[0] * dpi))
            height_px= int(round(fig_size[1] * dpi))
            fig = build_plotly_figure(
                state.config, state.last_all_data_points, state.last_tasks,
                state.gantt_config, width=width_px, height=height_px,
            )
            with open(out_path, 'wb') as fh:
                fh.write(render_png(fig, width_px, height_px))
            state.logger.info(f"Chart exported: {out_path}")
            return dbc.Alert(f"✓ Saved: {out_path}", color="success")
        except Exception as e:
            state.logger.error(f"Export error: {e}")
            return dbc.Alert(f"Export error: {e}", color="danger")

    # ── Plotly preview ────────────────────────────────────────────────────────
    @app.callback(
        Output('plotly-preview', 'figure'),
        Input('store-preview-ready', 'data'),
        prevent_initial_call=True,
    )
    def update_plotly_preview(ready):
        if not ready or state.last_all_data_points is None:
            return go.Figure()
        # No width/height passed here — figure uses autosize=True so it
        # fills the scrollable CSS container in the browser.
        # Explicit pixel dimensions are only used by the batch exporter.
        return build_plotly_figure(
            state.config, state.last_all_data_points,
            state.last_tasks or [], state.gantt_config,
        )

    # ── Data summary table ────────────────────────────────────────────────────
    @app.callback(
        Output('data-summary-table', 'children'),
        Input('store-series-summary', 'data'),
    )
    def update_data_summary(data):
        if not data:
            return html.P("Generate a chart to see data summary.", className="text-muted small")
        return dash_table.DataTable(
            data=data, columns=[{'name': c, 'id': c} for c in data[0].keys()],
            style_table={'overflowX': 'auto'},
            style_cell={'fontSize': '12px', 'padding': '4px 8px'},
            style_header={'fontWeight': 'bold', 'background': '#e8f4f8'},
        )

    # ── Event table ───────────────────────────────────────────────────────────
    @app.callback(
        Output('event-summary-table', 'children'),
        Input('store-task-summary', 'data'),
    )
    def update_event_table(data):
        if not data:
            return html.P("Generate a chart to see events.", className="text-muted small")
        return dash_table.DataTable(
            data=data, columns=[{'name': c, 'id': c} for c in data[0].keys()],
            style_table={'overflowX': 'auto'},
            style_cell={'fontSize': '11px', 'padding': '3px 6px'},
            style_header={'fontWeight': 'bold', 'background': '#f0e8f8'},
            page_size=20,
        )

    # ── Main log polling ──────────────────────────────────────────────────────
    @app.callback(
        Output('log-output', 'children'),
        Input('interval-log', 'n_intervals'),
        Input('btn-clear-log', 'n_clicks'),
    )
    def update_log(_, __):
        if ctx.triggered_id == 'btn-clear-log':
            state.log_lines.clear()
            return []
        return _log_spans(state.log_lines, _main_log_class)

    # ── Batch queue list ──────────────────────────────────────────────────────
    # Reacts to folder changes AND profile store changes so toggling configs
    # in Config Manager immediately reflects here.
    @app.callback(
        Output('batch-queue-list', 'children'),
        Output('btn-batch',        'disabled', allow_duplicate=True),
        Input('batch-config-folder', 'value'),
        Input('batch-data-folder',   'value'),
        Input('batch-output-folder', 'value'),
        Input('store-bp-order',      'data'),
        Input('store-gantt-loaded',  'data'),
        State('event-file-path',     'value'),
        prevent_initial_call='initial_duplicate',
    )
    def update_batch_readiness(cfg_folder, data_folder, out_folder,
                               bp_order, gantt_loaded, event_path):

        has_gantt  = bool(gantt_loaded)
        has_event  = bool(event_path and os.path.isfile(event_path))
        has_cfg    = bool(cfg_folder  and os.path.isdir(cfg_folder))
        has_data   = bool(data_folder and os.path.isdir(data_folder))
        has_output = bool(out_folder  and os.path.isdir(out_folder))

        nd = 0
        if has_data:
            nd = len([f for f in os.listdir(data_folder)
                      if f.lower().endswith(('.csv', '.txt'))])

        nc = 0
        config_names = []
        if has_cfg:
            _bpm = BatchProfileManager()
            _bpm.load(cfg_folder)
            paths = _bpm.get_ordered_paths(cfg_folder, fallback_alphabetical=True)
            paths = [p for p in paths
                     if os.path.basename(p) not in RESERVED_CONFIG_FILENAMES]
            nc           = len(paths)
            config_names = [os.path.basename(p) for p in paths]

        all_ready = all([has_gantt, has_event, has_cfg, has_data,
                         has_output, nc > 0, nd > 0])

        if not config_names:
            queue = html.Div(
                html.Small("No configs in run queue — set config folder and save a profile.",
                           className="text-muted fst-italic"),
            )
        else:
            total = nc * nd if nd else nc
            queue = html.Div([
                html.Div(
                    html.B(
                        f"Run queue — {nc} config(s) × {nd} data file(s) = {total} chart(s)"
                        if nd else f"Run queue — {nc} config(s)",
                        className="small text-muted",
                    ),
                    className="mb-1",
                ),
                html.Div([
                    dbc.Badge(
                        f"{i+1}. {name.replace('_config_composite_','').replace('.json','')}",
                        color="primary", className="me-1 mb-1",
                        style={"fontFamily": "monospace", "fontSize": "10px"},
                    )
                    for i, name in enumerate(config_names)
                ]),
            ])

        return queue, not all_ready

    # ── Run batch ─────────────────────────────────────────────────────────────
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
    def start_batch(_, cfg_folder, data_folder, out_folder, event_path, workers):
        errs = []
        if not state.gantt_config.is_loaded():       errs.append("Load a Gantt config first.")
        if not event_path or not os.path.isfile(event_path): errs.append("Event CSV not found.")
        if not cfg_folder  or not os.path.isdir(cfg_folder): errs.append("Config folder not found.")
        if not data_folder or not os.path.isdir(data_folder): errs.append("Data folder not found.")
        if not out_folder  or not os.path.isdir(out_folder): errs.append("Output folder not found.")
        if errs:
            return dbc.Alert(" | ".join(errs), color="warning"), False

        # Use the Batch Profile if one has been saved; fall back to
        # alphabetical order if no profile exists for this folder.
        _bpm = BatchProfileManager()
        _bpm.load(cfg_folder)
        config_files = _bpm.get_ordered_paths(cfg_folder, fallback_alphabetical=True)

        # Strip reserved infrastructure files (aesthetics.json, batch_profile.json)
        # from the work list — the batch worker does this too, but filtering here
        # ensures the 'total' count and status message are accurate.
        config_files = [p for p in config_files
                        if os.path.basename(p) not in RESERVED_CONFIG_FILENAMES]

        data_files   = sorted([os.path.join(data_folder, f)
                                for f in os.listdir(data_folder) if f.lower().endswith(('.csv', '.txt'))])
        if not config_files:
            return dbc.Alert("No JSON files in config folder.", color="warning"), False
        if not data_files:
            return dbc.Alert("No CSV/TXT files in data folder.", color="warning"), False

        n_workers = max(1, min(16, int(workers or 4)))
        total     = len(config_files) * len(data_files)

        state.batch_running = True
        state.batch_result  = None
        state.batch_stop_event.clear()
        state.batch_log.clear()

        def _done(result):
            state.batch_result  = result
            state.batch_running = False

        # Capture current UI chart settings so workers use the same
        # resolution/dpi even though they reload configs from disk.
        cc = state.config.get_chart_config()
        override_chart = {
            k: cc[k] for k in ('dpi', 'resolution_px', 'figure_size') if k in cc
        } or None

        # Resolve aesthetics.json from the config folder so every worker
        # loads the same master aesthetics alongside each per-chart config.
        aesthetics_path = os.path.join(cfg_folder, 'aesthetics.json')
        if not os.path.isfile(aesthetics_path):
            aesthetics_path = None   # falls back to DEFAULT_AESTHETICS_PATH in worker

        threading.Thread(
            target=_run_batch_worker,
            args=(config_files, data_files, event_path, out_folder, total, n_workers,
                  state.logger, state.gantt_config, state.batch_log,
                  state.batch_stop_event, _done, override_chart),
            kwargs={'aesthetics_path': aesthetics_path,
                    'system': load_settings().get('wz_system', '3P4W')},
            daemon=True,
        ).start()

        return dbc.Alert(f"⏳ Batch started — {total} charts, {n_workers} workers.", color="info"), True

    # ── Batch log polling + progress bar ──────────────────────────────────────
    @app.callback(
        Output('batch-log-output',         'children'),
        Output('btn-batch',                'disabled', allow_duplicate=True),
        Output('btn-estop',                'disabled'),
        Output('btn-estop',                'children'),
        Output('batch-status',             'children', allow_duplicate=True),
        Output('batch-progress-bar',       'value'),
        Output('batch-progress-bar',       'label'),
        Output('batch-progress-bar',       'color'),
        Output('batch-progress-bar',       'animated'),
        Output('batch-progress-container', 'style'),
        Output('batch-progress-label',     'children'),
        Input('interval-batch', 'n_intervals'),
        prevent_initial_call=True,
    )
    def poll_batch(_):
        spans       = _log_spans(state.batch_log, _batch_log_class)
        still_run   = state.batch_running
        stopped     = state.batch_stop_event.is_set()
        result      = state.batch_result
        estop_label = "⏹ Stopping…" if (still_run and stopped) else "⏹ E-Stop"

        # Parse progress from log — count "✓" and "✗" completion lines
        done_count  = sum(1 for line in state.batch_log
                          if '] ✓' in line or '] ✗' in line or '] ↷' in line)
        # Extract total from the BATCH STARTED line
        total_count = 0
        for line in state.batch_log:
            if 'BATCH STARTED' in line:
                import re as _re
                m = _re.search(r'(\d+) chart', line)
                if m:
                    total_count = int(m.group(1))
                break

        # Progress bar values
        if total_count > 0:
            pct      = int(round(done_count / total_count * 100))
            pb_label = f"{done_count}/{total_count}"
            pb_color = "danger" if stopped else ("success" if not still_run else "warning")
            pb_anim  = still_run and not stopped
            pb_style = {'display': 'block'}
            pl_label = (f"Rendering… {done_count}/{total_count} charts"
                        if still_run else f"Done — {done_count}/{total_count} charts")
        else:
            pct = 0; pb_label = ""; pb_color = "warning"
            pb_anim = False; pb_style = {'display': 'none'}; pl_label = ""

        # Hide progress container when idle and no result yet
        if not still_run and result is None and total_count == 0:
            pb_style = {'display': 'none'}

        if result is None:
            status = no_update
        elif result.get('failed'):
            status = dbc.Alert("✗ Batch failed — see Batch Log.", color="danger")
        elif result.get('stopped'):
            status = dbc.Alert(
                f"⚠ Batch stopped — {result['done'] - result['errors']}/{result['total']} "
                f"charts saved to {result['out_folder']}", color="warning")
        else:
            ok  = result['done'] - result['errors']
            clr = "success" if result['errors'] == 0 else "warning"
            status = dbc.Alert(f"✓ Batch complete — {ok}/{result['done']} charts saved "
                               f"to {result['out_folder']}", color=clr)

        return (spans, still_run, not still_run, estop_label, status,
                pct, pb_label, pb_color, pb_anim, pb_style, pl_label)

    # ── Resolution preset selector ───────────────────────────────────────────
    @app.callback(
        Output('settings-width',  'value', allow_duplicate=True),
        Output('settings-height', 'value', allow_duplicate=True),
        Input('preset-select', 'value'),
        prevent_initial_call=True,
    )
    def apply_preset(preset):
        res = RESOLUTION_PRESETS.get(preset)
        if not res:
            raise PreventUpdate   # 'Custom' — leave fields alone
        return res[0], res[1]

    # ── Settings modal ────────────────────────────────────────────────────────
    @app.callback(
        Output('settings-modal', 'is_open'),
        Output('settings-width', 'value'),
        Output('settings-height', 'value'),
        Output('settings-dpi', 'value'),
        Output('settings-font-scale', 'value'),
        Output('settings-lw-scale', 'value'),
        Input('btn-settings', 'n_clicks'),
        Input('btn-settings-cancel', 'n_clicks'),
        Input('btn-settings-apply', 'n_clicks'),
        State('settings-modal', 'is_open'),
        State('settings-width', 'value'),
        State('settings-height', 'value'),
        State('settings-dpi', 'value'),
        State('settings-font-scale', 'value'),
        State('settings-lw-scale', 'value'),
        prevent_initial_call=True,
    )
    def settings_modal(n_open, n_cancel, n_apply, is_open, w, h, dpi, fs, lws):
        trigger = ctx.triggered_id
        cc  = state.config.get_chart_config()
        rc  = state.config.get_responsive_config()
        sp  = state.config.get_subplot_params()
        cur_dpi = cc.get('dpi', DEFAULT_DPI)
        res     = cc.get('resolution_px')
        cur_w   = int(res[0]) if res else int(cc.get('figure_size', [20, 11])[0] * cur_dpi)
        cur_h   = int(res[1]) if res else int(cc.get('figure_size', [20, 11])[1] * cur_dpi)
        defaults = (cur_w, cur_h, cur_dpi,
                    rc.get('font_scale_factor', 1.0),
                    rc.get('linewidth_scale_factor', 1.0))

        if trigger == 'btn-settings':
            return (True, *defaults)
        if trigger == 'btn-settings-cancel':
            return (False, *defaults)
        # Apply
        try:
            nw, nh, nd = int(w), int(h), int(dpi)
            state.config.config.setdefault('chart', {}).update(
                {'dpi': nd, 'resolution_px': [nw, nh], 'figure_size': [nw / nd, nh / nd]})
            state.config.config.setdefault('responsive', {}).update(
                {'font_scale_factor': float(fs), 'linewidth_scale_factor': float(lws)})
            state.logger.info(f"Settings applied: {nw}×{nh} px @ {nd} DPI")
        except (TypeError, ValueError, ZeroDivisionError) as e:
            state.logger.warning(f"Settings apply error: {e}")
        return (False, w, h, dpi, fs, lws)

    # ── PPT build ─────────────────────────────────────────────────────────────
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
        if not img_folder or not os.path.isdir(img_folder):  errs.append("Image folder not found.")
        if not template   or not os.path.isfile(template):   errs.append("Template file not found.")
        if not out_folder or not os.path.isdir(out_folder):  errs.append("Output folder not found.")
        if not filename:                                       errs.append("Enter an output filename.")
        if errs:
            return dbc.Alert(" | ".join(errs), color="warning"), False

        safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)
        if not safe_name.lower().endswith('.pptx'):
            safe_name += '.pptx'
        out_path  = os.path.join(out_folder, safe_name)
        slide_dpi = int(dpi_val) if dpi_val else 96

        state.ppt_running = True
        state.ppt_result  = None
        state.ppt_log_lines.clear()
        threading.Thread(
            target=_ppt_thread,
            args=(state, img_folder, template, out_path, bool(auto_resize), slide_dpi),
            daemon=True,
        ).start()
        return dbc.Alert("⏳ Building PPTX…  watch the log below.", color="info"), True

    # ── PPT log polling ───────────────────────────────────────────────────────
    @app.callback(
        Output('ppt-log-output', 'children'),
        Output('btn-ppt-build', 'disabled', allow_duplicate=True),
        Output('ppt-build-status', 'children', allow_duplicate=True),
        Input('interval-ppt', 'n_intervals'),
        prevent_initial_call=True,
    )
    def poll_ppt(_):
        spans  = _log_spans(state.ppt_log_lines, _ppt_log_class)
        result = state.ppt_result
        if result is None:
            status = no_update
        elif result.get('success'):
            status = dbc.Alert(f"✓ PPTX saved: {result['path']}", color="success")
        else:
            status = dbc.Alert("✗ Build failed — see PPT Builder Log.", color="danger")
        return spans, state.ppt_running, status

    # ── Config Manager ────────────────────────────────────────────────────────
    register_batch_profile_callbacks(app, state)
    register_config_manager_callbacks(app, state)
    register_wizard_callbacks(app, state)

    # ── Auto-dismiss status messages ──────────────────────────────────────────
    # When a status message appears, clear it after 4 seconds by writing ""
    # back through a proper Dash Output — this keeps Dash's virtual DOM in
    # sync so repeated saves always re-trigger the indicator correctly.
    # A hidden dcc.Store per status ID acts as the timer sink.
    _auto_dismiss_ids = [
        'bp-status',
        'aes-save-status',
        'aes-load-status',
        'cfgmgr-action-status',
        'cfgmgr-folder-status',
        'cfg-save-status',
    ]
    for _sid in _auto_dismiss_ids:
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