# ──────────────────────────────────────────────────────────────────────────
# BACKGROUND THREADS
# ──────────────────────────────────────────────────────────────────────────

import os
import threading
import traceback
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Callable

from backend.processors import EventDataProcessor, event_plot_window
from backend.formats import ChartSkipped, DataFileError, load_chart_data, metric_peak
from backend.units import AUTO, apply_display_unit, base_unit
from backend.renderer import PngRenderer, RenderError
from backend.config import ConfigManager, GanttConfigManager
from backend.chart_gen import _build_output_filename
from backend.plotly_preview import build_plotly_figure
from utils.constants import DEFAULT_DPI, DEFAULT_FIGURE_SIZE, DEFAULT_AESTHETICS_PATH, RESERVED_CONFIG_FILENAMES

def run_batch(
    config_files:   List[str],
    data_files:     List[str],
    event_file:     str,
    out_folder:     str,
    total:          int,
    n_workers:      int,
    logger,                        # GUILogger instance
    gantt_config:   GanttConfigManager,
    batch_log:      List[str],     # shared list — append to update the UI
    stop_event:     threading.Event,
    on_done:        Callable,      # called with result dict when finished
    override_chart: dict = None,   # UI-applied chart overrides (dpi, resolution_px, figure_size)
    aesthetics_path: str = None,   # path to aesthetics.json; falls back to DEFAULT_AESTHETICS_PATH
    axis_overrides: dict = None,   # {config filename: {y_min, y_max, ...}}; None value = auto
    x_window:       tuple = None,  # (x_min, x_max) strings applied to every chart
    system:         str = '3P4W',  # wiring of the recordings: '3P4W' (with N) or '3P3W'
    units:          dict = None,   # {config filename: 'auto' | 'kW' | ...}; missing = auto
):
    """
    Runs the full batch render in a background thread.
    Exports Plotly figures as static PNGs via kaleido.
    All state is passed in explicitly — no DashApp reference needed.

    override_chart: if provided, these keys are merged into each config's
                    'chart' section after loading from disk, so UI settings
                    (resolution, dpi) take precedence over the JSON values.
    """
    blog = batch_log.append

    def ts():
        """Return current time as [HH:MM:SS] prefix."""
        return datetime.now().strftime("[%H:%M:%S]")

    _batch_start = datetime.now()

    blog("=" * 55)
    blog(f"{ts()} BATCH STARTED — {total} chart(s), {n_workers} parallel workers")
    blog(f"  Data files  : {len(data_files)}")
    blog(f"  Config files: {len(config_files)}")
    blog(f"  Output      : {out_folder}")
    blog(f"  System      : {system}")
    if override_chart:
        res = override_chart.get('resolution_px')
        dpi = override_chart.get('dpi')
        if res:
            blog(f"  Resolution  : {res[0]}×{res[1]} px @ {dpi} DPI (from UI settings)")
    blog("=" * 55)

    # One headless browser for the whole batch, shared by all workers
    # (renders are serialised inside; see backend/renderer.py).
    try:
        renderer = PngRenderer()
    except BaseException as e:   # noqa: BLE001 — browser missing / failed to launch
        reason = ("Could not start the image renderer — it needs Microsoft Edge or "
                  f"Google Chrome installed. ({e})")
        blog(f"{ts()} ABORTED — {reason}")
        on_done({'failed': True, 'reason': reason})
        return
    blog(f"{ts()} Image renderer started (shared browser process)")

    # Whatever happens, report back once — otherwise the UI waits forever.
    reported = []

    def _report(result):
        reported.append(True)
        on_done(result)

    try:
        _run_batch_body(
            config_files, data_files, event_file, out_folder, total,
            n_workers, logger, gantt_config, batch_log, stop_event,
            _report, override_chart, ts, _batch_start, aesthetics_path,
            axis_overrides, x_window, system, units, renderer,
        )
    except Exception as e:
        blog(f"{ts()} ABORTED — unexpected error: {e}\n{traceback.format_exc()}")
        if not reported:
            _report({'failed': True, 'reason': f"Unexpected error: {e}"})
    finally:
        renderer.close()
        blog(f"{ts()} Image renderer stopped")


def _run_batch_body(
    config_files:   List[str],
    data_files:     List[str],
    event_file:     str,
    out_folder:     str,
    total:          int,
    n_workers:      int,
    logger,
    gantt_config:   GanttConfigManager,
    batch_log:      List[str],
    stop_event:     threading.Event,
    on_done:        Callable,
    override_chart: dict = None,
    ts:             Callable = None,
    _batch_start:   datetime = None,
    aesthetics_path: str = None,
    axis_overrides: dict = None,
    x_window:       tuple = None,
    system:         str = '3P4W',
    units:          dict = None,
    renderer:       PngRenderer = None,
):
    """Inner body of run_batch — called after the image renderer is live."""
    blog = batch_log.append
    if ts is None:
        ts = lambda: datetime.now().strftime("[%H:%M:%S]")  # noqa: E731
    if _batch_start is None:
        _batch_start = datetime.now()
    if aesthetics_path is None:
        aesthetics_path = DEFAULT_AESTHETICS_PATH

    # Guard: filter out reserved files that must never be treated as chart configs.
    # aesthetics.json and batch_profile.json are infrastructure files, not charts.
    safe_configs = [
        p for p in config_files
        if os.path.basename(p) not in RESERVED_CONFIG_FILENAMES
    ]
    skipped = len(config_files) - len(safe_configs)
    if skipped:
        skipped_names = [os.path.basename(p) for p in config_files
                         if os.path.basename(p) in RESERVED_CONFIG_FILENAMES]
        blog(f"{ts()} ℹ Skipped {skipped} reserved file(s): {', '.join(skipped_names)}")
    config_files = safe_configs

    # Load event/task data ONCE — shared across all workers (read-only)
    event_proc = EventDataProcessor(logger=logger)
    if not event_proc.load_csv(event_file):
        blog(f"{ts()} ABORTED — failed to load the schedule: {event_proc.error}")
        on_done({'failed': True, 'reason': f"The schedule could not be read: {event_proc.error}"})
        return
    tasks = event_proc.get_tasks()
    blog(f"{ts()} Events loaded: {len(tasks)} tasks")

    # Time window precedence: explicit x_window (wizard) > chart x_min/x_max >
    # derived from the schedule > data extent.
    derived_window = event_plot_window(tasks)
    if not x_window and derived_window:
        blog(f"{ts()} Plot window from schedule: "
             f"{derived_window[0]:%Y-%m-%d %H:%M} → {derived_window[1]:%Y-%m-%d %H:%M} "
             f"(used where a chart has no x_min/x_max)")

    def _load_cfg(cfg_path):
        """Chart config with run-level overrides applied (None if invalid)."""
        cfg = ConfigManager(cfg_path, aesthetics_path=aesthetics_path, logger=logger)
        if not cfg.config:
            return None
        # UI-level overrides (resolution/dpi) on top of the JSON values.
        if override_chart:
            cfg.config.setdefault('chart', {}).update(override_chart)
        # Run-level axis overrides from the wizard: time window for every
        # chart, then per-chart Y limits (None = auto-fit to data).
        axis = cfg.config.setdefault('axis', {})
        if x_window:
            axis['x_min'], axis['x_max'] = x_window
        elif derived_window and not (axis.get('x_min') and axis.get('x_max')):
            axis['x_min'], axis['x_max'] = (d.strftime('%Y-%m-%d %H:%M:%S') for d in derived_window)
        for k, v in ((axis_overrides or {}).get(os.path.basename(cfg_path)) or {}).items():
            if v is None:
                axis.pop(k, None)
            else:
                axis[k] = v
        return cfg

    # Display units: an auto-unit chart with Auto Y takes its unit from the
    # largest reading across ALL files, so every slide of that chart matches.
    units = units or {}
    batch_peak = {}
    peak_window = None
    if x_window:
        peak_window = tuple(datetime.strptime(v, '%Y-%m-%d %H:%M:%S') for v in x_window)
    elif derived_window:
        peak_window = derived_window
    for cfg_path in config_files:
        name = os.path.basename(cfg_path)
        cfg  = _load_cfg(cfg_path)
        if (cfg is None or units.get(name, AUTO) != AUTO or not base_unit(cfg.config)
                or not cfg.config.get('metric')):
            continue
        axis = cfg.config['axis']
        if axis.get('y_min') is not None and axis.get('y_max') is not None:
            continue                           # unit follows the fixed limits
        # Reverse order leaves the first files in the parse cache for rendering.
        peaks = [metric_peak(p, cfg.config['metric'], system, peak_window)
                 for p in reversed(data_files)]
        peaks = [p for p in peaks if p is not None]
        if peaks:
            batch_peak[name] = max(peaks)

    # Build all work items upfront
    work_items = []
    for data_path in data_files:
        for cfg_path in config_files:
            out_name = _build_output_filename(data_path, cfg_path)
            work_items.append((data_path, cfg_path,
                               os.path.join(out_folder, out_name), out_name))

    done_count = 0
    errors     = []
    succeeded  = set()
    no_overlap = set()   # data files with no samples inside the plot window
    skipped    = []      # charts a file cannot supply (e.g. totals-only power)
    lock       = threading.Lock()

    def _render_one(item):
        """Worker: load data + config, build Plotly figure, save as PNG via kaleido."""
        data_path, cfg_path, out_path, out_name = item
        cfg_name  = os.path.basename(cfg_path)
        data_name = os.path.basename(data_path)

        # Each worker reloads the config fresh from disk, then applies the
        # run-level overrides (resolution, time window, Y limits).
        cfg = _load_cfg(cfg_path)
        if cfg is None:
            return out_name, f"SKIPPED (invalid config): {cfg_name}", None
        axis = cfg.config['axis']

        # Each data file is parsed once and shared by every chart (formats cache).
        try:
            all_dp = load_chart_data(cfg, data_path, system)
        except ChartSkipped as e:
            chart = os.path.splitext(cfg_name)[0]
            return out_name, None, f"{data_name}: {chart} not drawn — {e}."
        except DataFileError as e:
            return out_name, f"FAILED: {data_name} / {cfg_name} — {e}", None
        except Exception as e:
            return out_name, f"FAILED (data load): {data_name} — {e}", None

        apply_display_unit(cfg, all_dp, units.get(cfg_name, AUTO), batch_peak.get(cfg_name))

        try:
            win = [datetime.strptime(axis[k], '%Y-%m-%d %H:%M:%S') for k in ('x_min', 'x_max')]
        except (KeyError, TypeError, ValueError):
            win = None
        if win and not any(win[0] <= dp.timestamp <= win[1] for pts in all_dp for dp in pts):
            with lock:
                no_overlap.add(data_name)

        try:
            # Each worker gets its own GanttConfigManager to avoid shared color_index
            gantt_copy = GanttConfigManager(
                gantt_config.config_path
                if gantt_config.is_loaded() else None)

            # Derive exact pixel dimensions from config (same as Matplotlib).
            # Pass them into build_plotly_figure so the layout is constructed
            # at the correct size — not stretched post-hoc by kaleido.
            cc         = cfg.get_chart_config()
            dpi        = cc.get('dpi', DEFAULT_DPI)
            fig_size   = cc.get('figure_size', DEFAULT_FIGURE_SIZE)
            width_px   = int(round(fig_size[0] * dpi))
            height_px  = int(round(fig_size[1] * dpi))

            fig = build_plotly_figure(cfg, all_dp, tasks, gantt_copy,
                                      width=width_px, height=height_px)

            renderer.save(fig, out_path, width_px, height_px)
            return out_name, None, None   # success

        except RenderError as e:
            return out_name, f"FAILED: {out_name} — {e}", None
        except Exception as e:
            return out_name, f"ERROR: {out_name} — {e}\n{traceback.format_exc()}", None

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_render_one, item): item for item in work_items}
        stopped = False
        for future in as_completed(futures):
            # Check E-stop between completed futures
            if stop_event.is_set() and not stopped:
                stopped = True
                blog(f"{ts()} ⚠ E-Stop signal received — cancelling remaining queued charts…")
                cancelled = sum(1 for f in futures if f.cancel())
                blog(f"  {cancelled} queued chart(s) cancelled")

            try:
                out_name, err, skip = future.result()
            except CancelledError:
                continue
            with lock:
                done_count += 1
                progress = f"[{done_count}/{total}]"
                if err:
                    blog(f"  {ts()} {progress} ✗ {err}")
                    errors.append(err)
                elif skip:
                    blog(f"  {ts()} {progress} ↷ {skip}")
                    skipped.append(skip)
                else:
                    blog(f"  {ts()} {progress} ✓ {out_name}")
                    succeeded.add(out_name)

    blog("\n" + "=" * 55)
    saved   = done_count - len(errors) - len(skipped)
    elapsed = (datetime.now() - _batch_start).total_seconds()
    elapsed_str = f"{int(elapsed // 60)}m {elapsed % 60:.1f}s" if elapsed >= 60 else f"{elapsed:.1f}s"
    if stopped:
        blog(f"{ts()} BATCH STOPPED — {saved}/{done_count} charts saved (of {total} total)")
    else:
        blog(f"{ts()} BATCH COMPLETE — {saved}/{done_count} charts saved")
    blog(f"  Total time  : {elapsed_str}")
    if total > 0 and done_count > 0:
        blog(f"  Avg per chart: {elapsed / done_count:.1f}s")
    if errors:
        blog(f"{len(errors)} error(s):")
        for e in errors:
            blog(f"  • {e}")
    warnings = [f"{name}: no data inside the plot window — check the file matches the schedule's dates."
                for name in sorted(no_overlap)] + sorted(skipped)
    for w in warnings:
        blog(f"⚠ {w}")
    blog(f"Output: {out_folder}")
    blog("=" * 55)

    on_done({
        'failed':     False,
        'stopped':    stopped,
        'done':       done_count,
        'total':      total,
        'errors':     len(errors),
        'error_messages': [e.splitlines()[0] for e in errors],   # no tracebacks
        'out_folder': out_folder,
        # Successful outputs in work order (data file × config order) — used
        # by the PPT builder so slide order is deterministic.
        'outputs':    [p for _, _, p, n in work_items if n in succeeded],
        'warnings':   warnings,
    })