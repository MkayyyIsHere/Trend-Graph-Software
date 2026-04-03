# =============================================================================
# CHART GENERATION  (unchanged — Matplotlib 2_backend)
# =============================================================================
import re
import io
import os
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use('Agg')
matplotlib.interactive(False)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker

from backend.models import DataPoint, Task
from backend.config import ConfigManager, GanttConfigManager
from utils.constants import DEFAULT_FIGURE_SIZE, DEFAULT_DPI
from utils.logger import GUILogger


from datetime import datetime, timedelta

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
                            facecolor='none', edgecolor=ec,
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

        lc = self.config.config.get('legend', {})
        legend_width_px = lc.get('width_px', sp.get('legend_width_px', None))
        if legend_width_px is not None:
            res = cc.get('resolution_px')
            if res:
                fig_w_px = res[0]
            else:
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

        lc            = self.config.config.get('legend', {})
        PAD_TOP       = lc.get('pad_top',       rc.get('legend_pad_top',       0.5))
        PAD_SEP_ABOVE = lc.get('pad_sep_above', rc.get('legend_pad_sep_above', 0.4))
        PAD_SEP_BELOW = lc.get('pad_sep_below', rc.get('legend_pad_sep_below', 0.4))
        GAP_SLOTS     = lc.get('gap_slots',     rc.get('legend_gap_slots',     0.5))
        col_tid_w     = 0.30
        col_desc_x    = col_tid_w + 0.04
        pad_x         = 0.03
        legend_wrap_w = lc.get('wrap_width', max(10, int((1.0 - col_desc_x - pad_x) / (legend_fs * 0.0012))))

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
            cc = self.config.get_chart_config()
            self.fig.savefig(output_path,
                             dpi=cc.get('dpi', DEFAULT_DPI),
                             bbox_inches=None,
                             facecolor=cc.get('background_color', '#ffffff'),
                             edgecolor='none', pad_inches=0)
            self._log(f"Chart saved to: {output_path}")
        except Exception as e:
            self._log(f"Failed to save chart: {e}", 'ERROR')

    def to_png_bytes(self) -> bytes:
        """Return the current figure as PNG bytes (for browser display)."""
        buf = io.BytesIO()
        cc = self.config.get_chart_config()
        self.fig.savefig(buf, format='png',
                         dpi=cc.get('dpi', DEFAULT_DPI),
                         bbox_inches=None,
                         facecolor=cc.get('background_color', '#ffffff'),
                         edgecolor='none', pad_inches=0)
        buf.seek(0)
        return buf.read()




# =============================================================================
# FILENAME HELPER  (unchanged)
# =============================================================================

def _build_output_filename(data_path: str, cfg_path: str) -> str:
    data_stem = os.path.splitext(os.path.basename(data_path))[0]
    cfg_stem  = os.path.splitext(os.path.basename(cfg_path))[0]
    safe      = re.sub(r'[^\w\-_]', '_', f"{data_stem}__{cfg_stem}")
    return f"{safe}.png"