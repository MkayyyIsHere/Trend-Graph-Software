# ──────────────────────────────────────────────────────────────────────────
# BACKGROUND THREADS
# ──────────────────────────────────────────────────────────────────────────

import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Callable

from backend.processors import SeriesDataProcessor, EventDataProcessor
from backend.config import ConfigManager, GanttConfigManager
from backend.chart_gen import _build_output_filename
from backend.plotly_preview import build_plotly_figure
from utils.constants import DEFAULT_DPI, DEFAULT_FIGURE_SIZE


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

    blog("=" * 55)
    blog(f"BATCH STARTED — {total} chart(s), {n_workers} parallel workers")
    blog(f"  Data files  : {len(data_files)}")
    blog(f"  Config files: {len(config_files)}")
    blog(f"  Output      : {out_folder}")
    if override_chart:
        res = override_chart.get('resolution_px')
        dpi = override_chart.get('dpi')
        if res:
            blog(f"  Resolution  : {res[0]}×{res[1]} px @ {dpi} DPI (from UI settings)")
    blog("=" * 55)

    # Load event/task data ONCE — shared across all workers (read-only)
    event_proc = EventDataProcessor(logger=logger)
    if not event_proc.load_csv(event_file):
        blog("ABORTED — failed to load event CSV")
        on_done({'failed': True})
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
        """Worker: load data + config, build Plotly figure, save as PNG via kaleido."""
        data_path, cfg_path, out_path, out_name = item
        cfg_name  = os.path.basename(cfg_path)
        data_name = os.path.basename(data_path)

        cfg = ConfigManager(cfg_path)
        if not cfg.config:
            return out_name, f"SKIPPED (invalid config): {cfg_name}"

        # Apply UI-level overrides (resolution/dpi) on top of the JSON values.
        # This ensures that settings changed in the Settings modal are honoured
        # even though each worker reloads the config fresh from disk.
        if override_chart:
            cfg.config.setdefault('chart', {}).update(override_chart)

        all_dp = []
        for sc in cfg.get_all_series_configs():
            proc = SeriesDataProcessor(
                logger=logger,
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
            # Each worker gets its own GanttConfigManager to avoid shared color_index
            gantt_copy = GanttConfigManager(
                gantt_config.config_path
                if gantt_config.is_loaded() else None)

            fig = build_plotly_figure(cfg, all_dp, tasks, gantt_copy)

            # Derive exact pixel dimensions from config (same as Matplotlib).
            # Plotly/kaleido accepts width & height in pixels directly;
            # scale=1 means no further multiplication is applied.
            cc         = cfg.get_chart_config()
            dpi        = cc.get('dpi', DEFAULT_DPI)
            fig_size   = cc.get('figure_size', DEFAULT_FIGURE_SIZE)
            width_px   = int(round(fig_size[0] * dpi))
            height_px  = int(round(fig_size[1] * dpi))

            fig.write_image(out_path, format='png',
                            width=width_px, height=height_px, scale=1)
            return out_name, None   # success

        except Exception as e:
            return out_name, f"ERROR: {out_name} — {e}\n{traceback.format_exc()}"

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_render_one, item): item for item in work_items}
        stopped = False
        for future in as_completed(futures):
            # Check E-stop between completed futures
            if stop_event.is_set() and not stopped:
                stopped = True
                blog("⚠ E-Stop signal received — cancelling remaining queued charts…")
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

    on_done({
        'failed':     False,
        'stopped':    stopped,
        'done':       done_count,
        'total':      total,
        'errors':     len(errors),
        'out_folder': out_folder,
    })