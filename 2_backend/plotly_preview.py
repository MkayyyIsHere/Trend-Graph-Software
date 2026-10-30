# =============================================================================
# PLOTLY PREVIEW BUILDER  (faithful translation of the Matplotlib chart)
# =============================================================================

import math
import textwrap as _textwrap
from typing import Dict, List, Tuple

import plotly.graph_objects as go

from backend.models import DataPoint, Task
from backend.config import ConfigManager, GanttConfigManager
from datetime import datetime


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' to 'rgba(r,g,b,alpha)'."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r},{g},{b},{alpha})'


def _nice_interval(span: float, target_count: int = 6) -> float:
    """Return a 'nice' tick interval for *span* targeting ~target_count major ticks.

    Rounds *span / target_count* up to the nearest value in {1, 2, 2.5, 5} × 10^n
    so that tick labels fall on clean round numbers.
    """
    import math
    if span <= 0 or target_count <= 0:
        return 1.0
    raw = span / target_count
    mag = 10 ** math.floor(math.log10(abs(raw)))
    n = raw / mag
    if n < 1.5:
        nice = 1.0
    elif n < 2.25:
        nice = 2.0
    elif n < 3.5:
        nice = 2.5
    elif n < 7.5:
        nice = 5.0
    else:
        nice = 10.0
    return nice * mag


# (max window hours, major tick min, minor tick min) — keeps ~15–40 labels on the x axis
_X_TICK_STEPS = [
    (4,   15,  5),
    (18,  30,  10),
    (36,  60,  15),
    (72,  120, 30),
    (168, 360, 60),
]


def _x_tick_spacing(x_range):
    """Return (major_ms, minor_ms) x-axis tick spacing for the plotted window."""
    hours = 16.0
    if x_range:
        hours = (x_range[1] - x_range[0]).total_seconds() / 3600
    for max_h, major_min, minor_min in _X_TICK_STEPS:
        if hours <= max_h:
            return major_min * 60_000, minor_min * 60_000
    return 720 * 60_000, 120 * 60_000


def build_plotly_figure(config: ConfigManager,
                         all_series_data: List[List[DataPoint]],
                         tasks: List[Task],
                         gantt_config: GanttConfigManager = None,
                         width: int = None,
                         height: int = None) -> go.Figure:
    """
    Build an interactive Plotly version of the composite chart that faithfully
    mirrors the Matplotlib export:
      • Colored vertical bands for every task
      • Bidirectional arrows (◄►) at label height spanning start→end
      • Collision-free Test ID labels stacked top-down (same algorithm as mpl)
      • Right-side legend table:
            ─ series color swatch + name
            ─ separator
            ─ Test ID (bold) | Description (normal)
    """

    fig = go.Figure()
    ac      = config.get_axis_config()
    cc      = config.get_chart_config()
    rc      = config.get_responsive_config()
    all_cfg = config.get_all_series_configs()

    # ── Y-axis data range ────────────────────────────────────────────────────
    y_min_cfg = ac.get('y_min')
    y_max_cfg = ac.get('y_max')
    flat_points: List[DataPoint] = [dp for pts in all_series_data for dp in pts]

    # Actual data extent — used for label placement regardless of axis limits.
    # Respect per-series abs_value flag so placement matches what is plotted.
    if flat_points:
        abs_flags = {i: sc.get('abs_value', False) for i, sc in enumerate(all_cfg)}
        vals = []
        for idx, data_points in enumerate(all_series_data):
            use_abs = abs_flags.get(idx, False)
            for dp in data_points:
                vals.append(abs(dp.value) if use_abs else dp.value)
        actual_data_min, actual_data_max = min(vals), max(vals)
    else:
        actual_data_min, actual_data_max = 0.0, 1.0

    # Axis display range — honours config limits when set
    if y_min_cfg is not None and y_max_cfg is not None:
        data_min, data_max = float(y_min_cfg), float(y_max_cfg)
    else:
        data_min, data_max = actual_data_min, actual_data_max
    data_range = data_max - data_min or 1.0

    # ── Series lines ─────────────────────────────────────────────────────────
    for idx, data_points in enumerate(all_series_data):
        if not data_points:
            continue
        sc        = all_cfg[idx] if idx < len(all_cfg) else all_cfg[-1]
        name      = sc.get('name', f'Series {idx + 1}')
        color     = sc.get('line_color', '#1f77b4')
        linewidth = sc.get('linewidth', 1.5)
        alpha     = sc.get('alpha', 0.65)
        sorted_pts = sorted(data_points, key=lambda dp: dp.timestamp)

        segments, seg = [], []
        for dp in sorted_pts:
            if seg and (dp.timestamp - seg[-1].timestamp).total_seconds() > 2.0:
                segments.append(seg); seg = []
            seg.append(dp)
        if seg:
            segments.append(seg)

        use_abs = sc.get('abs_value', False)
        first = True
        for segment in segments:
            values = [abs(dp.value) if use_abs else dp.value for dp in segment]
            fig.add_trace(go.Scatter(
                x=[dp.timestamp for dp in segment],
                y=values,
                mode='lines',
                name=name if first else None,
                showlegend=first,
                legendgroup=name,
                line=dict(color=color, width=linewidth),
                opacity=alpha,
                hovertemplate='%{x|%H:%M:%S %b %d}<br>%{y:.4f}<extra>' + name + '</extra>',
            ))
            first = False

    # ── Gantt overlay ─────────────────────────────────────────────────────────
    fallback_palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
    task_colors: Dict[str, str] = {}
    color_idx = 0

    if tasks and gantt_config and gantt_config.is_loaded():
        # reset color counter so colors are assigned fresh (same as mpl)
        gantt_config.color_index = 0

    # Assign colors & collect task data
    task_data = []
    for task in tasks:
        if gantt_config and gantt_config.is_loaded():
            color = gantt_config.get_color_for_test_id(task.test_id)
        else:
            if task.test_id not in task_colors:
                task_colors[task.test_id] = fallback_palette[color_idx % len(fallback_palette)]
                color_idx += 1
            color = task_colors[task.test_id]

        if task.is_normalization:
            fill_rgba = 'rgba(0,0,0,0)'
            edge_rgba = 'rgba(128,128,128,0.35)'
            color     = '#808080'
        else:
            fill_rgba = 'rgba(0,0,0,0)'
            edge_rgba = _hex_to_rgba(color, 0.70)

        task_data.append({
            'task': task, 'color': color,
            'fill': fill_rgba, 'edge': edge_rgba,
        })

        # Colored band (below data lines) — no border on vrect itself
        fig.add_vrect(
            x0=task.start_time, x1=task.end_time,
            fillcolor=fill_rgba,
            line=dict(width=0),
            layer='below',
        )
        # Left edge only
        fig.add_shape(
            type='line',
            x0=task.start_time, x1=task.start_time,
            y0=0, y1=1,
            xref='x', yref='y domain',
            line=dict(color=edge_rgba, width=1),
            layer='below',
        )
        # Right edge only
        fig.add_shape(
            type='line',
            x0=task.end_time, x1=task.end_time,
            y0=0, y1=1,
            xref='x', yref='y domain',
            line=dict(color=edge_rgba, width=1),
            layer='below',
        )

    # ── Collision-free label rows (mirrors matplotlib algorithm) ─────────────
    #
    # We work in data-units for Y, datetime for X.
    # Rows stack downward from (data_max - 3 % gap).
    # X-collision is checked in timestamp seconds (no renderer needed in Plotly).
    #
    label_fs   = rc.get('legend_fontsize_base', 13) * rc.get('font_scale_factor', 1.0)
    # Estimate row height as a fraction of data range (same cap logic as mpl)
    # Use actual data range (not axis limits) so labels aren't clipped
    actual_data_range = actual_data_max - actual_data_min or 1.0
    _t         = max(0.0, min(1.0, (actual_data_range - 1.0) / (5000.0 - 1.0)))
    cap_pct    = 0.06 * (1 - _t) + 0.03 * _t
    row_step   = data_range * cap_pct

    # Place labels near top of the axis display range (not just data max)
    base_y     = data_max - data_range * 0.03

    # Estimate character width in seconds to detect X overlaps
    # Use a rough approximation: 1 char ≈ label_fs * 0.5 px, figure is ~2560 px wide
    # Map pixel width to time using x_range
    x_min_dt, x_max_dt = None, None
    if ac.get('x_min') and ac.get('x_max'):
        try:
            x_min_dt = datetime.strptime(ac['x_min'], '%Y-%m-%d %H:%M:%S')
            x_max_dt = datetime.strptime(ac['x_max'], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            pass
    if x_min_dt is None and flat_points:
        all_ts = [dp.timestamp for dp in flat_points]
        all_ts += [t for task in tasks for t in (task.start_time, task.end_time)]
        x_min_dt, x_max_dt = min(all_ts), max(all_ts)

    if x_min_dt and x_max_dt:
        total_secs = max((x_max_dt - x_min_dt).total_seconds(), 1)
    else:
        total_secs = 86400

    # Rough char width in seconds (label_fs px out of 1200 px plot width)
    char_width_sec = total_secs * (label_fs * 0.6) / 1200.0

    row_slots: Dict[int, List[Tuple[float, float]]] = {}
    assigned_rows = []
    extents_sec   = []  # (x0_sec, x1_sec) per task

    epoch = x_min_dt or datetime(2000, 1, 1)

    for td in task_data:
        task  = td['task']
        s_sec = (task.start_time - epoch).total_seconds()
        e_sec = (task.end_time   - epoch).total_seconds()
        lbl   = task.display_id
        lbl_w = len(lbl) * char_width_sec
        x0_s  = min(s_sec, s_sec)            # label starts at task start
        x1_s  = max(e_sec, s_sec + lbl_w)    # extends to cover the label

        extents_sec.append((x0_s, x1_s))

        # Find a free row
        row = 0
        while any(not (x1_s <= sx0 or x0_s >= sx1)
                  for sx0, sx1 in row_slots.get(row, [])):
            row += 1
        row_slots.setdefault(row, []).append((x0_s, x1_s))
        assigned_rows.append(row)

    # Draw arrows + labels
    for td, row, (x0_s, x1_s) in zip(task_data, assigned_rows, extents_sec):
        task    = td['task']
        color   = td['color']
        arrow_y = base_y - row * row_step
        label_y = arrow_y + row_step * 0.30

        # ── Bidirectional arrow as a shape line + two arrowheads ─────────────
        # Plotly doesn't support <-> arrowstyle natively, so we draw:
        #   • a dotted line from start to end at arrow_y
        #   • left arrowhead annotation at start
        #   • right arrowhead annotation at end
        #   • label annotation slightly above arrow_y

        # Dotted line (drawn as a zero-height filled shape)
        fig.add_shape(
            type='line',
            x0=task.start_time, x1=task.end_time,
            y0=arrow_y, y1=arrow_y,
            line=dict(color=color, width=1.2, dash='dot'),
            layer='above',
        )

        # Left arrowhead  ◄
        fig.add_annotation(
            x=task.start_time, y=arrow_y,
            ax=task.end_time,  ay=arrow_y,
            xref='x', yref='y', axref='x', ayref='y',
            showarrow=True,
            arrowhead=2, arrowsize=0.8, arrowwidth=1.2,
            arrowcolor=color,
            text='',
        )

        # Right arrowhead  ►
        fig.add_annotation(
            x=task.end_time,   y=arrow_y,
            ax=task.start_time, ay=arrow_y,
            xref='x', yref='y', axref='x', ayref='y',
            showarrow=True,
            arrowhead=2, arrowsize=0.8, arrowwidth=1.2,
            arrowcolor=color,
            text='',
        )

        # Test ID label (with white background box, matching mpl bbox style)
        fig.add_annotation(
            x=task.start_time, y=label_y,
            xref='x', yref='y',
            text=f'<b>{task.display_id}</b>',
            showarrow=False,
            font=dict(size=label_fs, color=color,
                      family=rc.get('legend_font_family', 'sans-serif')),
            xanchor='left', yanchor='bottom',
            bgcolor='rgba(255,255,255,0.85)',
            bordercolor=color,
            borderwidth=0.8,
            borderpad=2,
        )

    # ── Layout ────────────────────────────────────────────────────────────────
    # All aesthetic values come from config (aesthetics.json → per-chart merge).
    # Nothing is hardcoded here.

    bg_color    = cc.get('background_color', '#ffffff')
    title_fs    = rc.get('title_fontsize_base', 20) * rc.get('font_scale_factor', 1.0)
    label_fs_ax = rc.get('axis_label_fontsize_base', 15) * rc.get('font_scale_factor', 1.0)
    tick_fs     = rc.get('tick_fontsize_base', 12) * rc.get('font_scale_factor', 1.0)
    font_family = rc.get('legend_font_family', 'sans-serif')

    gc          = config.get_grid_config()
    grid_alpha  = gc.get('alpha', 0.3)
    grid_color_hex = gc.get('color', '#505050')
    # Convert hex+alpha to rgba for plotly
    _h = grid_color_hex.lstrip('#')
    _gr, _gg, _gb = int(_h[0:2], 16), int(_h[2:4], 16), int(_h[4:6], 16)
    grid_rgba   = f'rgba({_gr},{_gg},{_gb},{grid_alpha})'

    y_range = None
    if y_min_cfg is not None and y_max_cfg is not None:
        y_range = [float(y_min_cfg), float(y_max_cfg)]
    elif flat_points:
        pad = data_range * 0.05
        # Preserve sign: pad both ends symmetrically so negative values stay visible
        y_range = [data_min - pad, data_max + pad]

    # ── Y-axis fine tick interval (4 subdivisions per major tick, all labelled) ─
    # Plotly does not support different font sizes per tick natively, so all
    # labelled ticks appear at the same size in the live preview.  The batch
    # export (chart_gen.py) applies proper 75 % / #808080 minor-label styling.
    y_dtick = None
    y_minor_dtick = None
    if y_range is not None:
        _y_span = float(y_range[1]) - float(y_range[0])
        if _y_span > 0:
            _y_major_iv = ac.get('y_major_interval')
            _major_iv = float(_y_major_iv) if _y_major_iv is not None \
                        else _nice_interval(_y_span)
            y_dtick       = _major_iv / 2.0   # labelled ticks: major + midpoint
            y_minor_dtick = _major_iv / 4.0   # tick marks at ¼ and ¾ — no labels

    # Always compute x_range from config or full data extent so Live Preview
    # shows the same axis span as the exported image (autosize only affects
    # the figure's pixel dimensions, not the data range).
    x_range = None
    if x_min_dt and x_max_dt:
        x_range = [x_min_dt, x_max_dt]
    elif flat_points:
        all_ts = [dp.timestamp for dp in flat_points]
        if tasks:
            all_ts += [t for task in tasks for t in (task.start_time, task.end_time)]
        if all_ts:
            x_range = [min(all_ts), max(all_ts)]

    x_major_ms, x_minor_ms = _x_tick_spacing(x_range)

    sp = config.get_subplot_params()

    # Convert subplot_params fractions to Plotly pixel margins when dimensions
    # are known (batch export). Fall back to sensible defaults for browser preview.
    _right  = sp.get('right',  0.75)
    _left   = sp.get('left',   0.03)
    _top    = sp.get('top',    0.95)
    _bottom = sp.get('bottom', 0.06)
    leg_x   = sp.get('legend_x', _right + 0.01)
    leg_y   = sp.get('legend_y', 1.0)

    # Fixed small margins — layout controlled via xaxis/yaxis domain
    # mar_t scales with how much space is above the plot for the title
    _gap_top = 1.0 - _top
    mar_t = max(50, int(_gap_top * 600))  # at least 50px, grows with gap
    mar_l, mar_r, mar_b = 80, 20, 80

    # Legend annotation width from unused right fraction
    _fig_w = width if width else 1200
    legend_w_px = max(200, int((1.0 - _right) * _fig_w) - 60)

    fig.update_layout(
        title=dict(
            text=cc.get('title', 'Data Over Time with Events'),
            font=dict(size=title_fs, family=font_family),
            x=0.5,
            y=min(0.99, _top + _gap_top * 0.5),
            xref='paper',
            yref='paper',
            automargin=True,
        ),
        xaxis=dict(
            domain=[_left, _right],
            title=dict(text=ac.get('x_label', 'Date & Time'),
                       font=dict(size=label_fs_ax, family=font_family)),
            range=x_range,
            autorange=(x_range is None),
            showgrid=gc.get('visible', True),
            gridcolor=grid_rgba,
            tickfont=dict(size=tick_fs, family=font_family),
            tickformat='%H:%M<br>%b %d',
            tickmode='linear',
            dtick=x_major_ms,           # labelled tick spacing (ms), scales with window
            tick0='2000-01-01 00:00:00',
            showspikes=True, spikemode='across', spikesnap='cursor',
            spikedash='solid', spikecolor='gray', spikethickness=1,
            showline=True, linecolor=grid_rgba, linewidth=1.5,
            ticks='outside', ticklen=6, tickwidth=1, tickcolor=grid_rgba,
            minor=dict(ticks='outside', ticklen=3, tickwidth=0.7,
                       dtick=x_minor_ms,   # unlabelled minor ticks (ms)
                       tickcolor=f'rgba({_gr},{_gg},{_gb},{grid_alpha * 0.7:.2f})'),
        ),
        yaxis=dict(
            domain=[_bottom, _top],
            title=dict(text=ac.get('y_label', 'Value'),
                       font=dict(size=label_fs_ax, family=font_family)),
            range=y_range,
            showgrid=gc.get('visible', True),
            gridcolor=grid_rgba,
            tickfont=dict(size=tick_fs, family=font_family),
            showline=True, linecolor=grid_rgba, linewidth=1.5,
            ticks='outside', ticklen=6, tickwidth=1, tickcolor=grid_rgba,
            # Labels at major + midpoint; ¼ and ¾ positions are tick-mark-only.
            # minor.dtick is intentionally omitted here — it works in the browser
            # but is silently ignored by kaleido for linear/numeric axes.
            # Minor tick marks are drawn as explicit shapes below (works everywhere).
            **({'tickmode': 'linear', 'dtick': y_dtick, 'tick0': 0}
               if y_dtick is not None else {}),
        ),
        plot_bgcolor=bg_color,
        paper_bgcolor=bg_color,
        hovermode='x unified',
        showlegend=True,
        legend=dict(
            orientation='v',
            x=leg_x, xanchor='left',
            y=leg_y, yanchor='top',
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0)',
            borderwidth=0,
            font=dict(size=label_fs, family=font_family),
            title=dict(text=''),
        ),
        margin=dict(l=mar_l, r=mar_r, t=mar_t, b=mar_b),
        # When explicit pixel dims are provided (batch export): fix the size
        # so kaleido renders at exactly the right resolution.
        # When no dims given (browser preview): autosize=True so the figure
        # fills its CSS container instead of overflowing the page.
        **(dict(width=width, height=height, autosize=False)
           if width and height else dict(autosize=True)),
    )

    # ── Y-axis minor tick marks (explicit shapes) ────────────────────────────
    # Plotly's minor.dtick works in the browser but is silently dropped by
    # kaleido (the PNG export engine) on linear/numeric axes.  Drawing them
    # as paper-coordinate shapes is reliable in both environments.
    #
    # Pattern (matches chart_gen.py Matplotlib output):
    #   MAJOR label | ¼ spike | ½ label | ¾ spike | MAJOR label
    if y_minor_dtick is not None and y_dtick is not None and y_range is not None:
        _minor_tick_color = f'rgba({_gr},{_gg},{_gb},{grid_alpha * 0.7:.2f})'
        # Convert 3-pixel tick length to a paper-x fraction so it scales
        # correctly at any export resolution.
        _tick_px   = 3
        _tick_frac = _tick_px / max(1, _fig_w)
        _tol       = y_minor_dtick * 0.001

        # Start one step before range to catch positions clipped by y_range[0]
        _pos = math.floor(y_range[0] / y_minor_dtick) * y_minor_dtick
        while _pos <= y_range[1] + _tol:
            # Skip positions that coincide with a labeled (major/midpoint) tick
            _rem = _pos % y_dtick
            if _rem < 0:
                _rem += y_dtick
            _is_labeled = _rem < _tol or abs(_rem - y_dtick) < _tol

            if not _is_labeled and (y_range[0] - _tol) <= _pos <= (y_range[1] + _tol):
                fig.add_shape(
                    type='line',
                    # Extends 3 px to the LEFT of the y-axis spine (paper coords)
                    x0=_left - _tick_frac, x1=_left,
                    y0=_pos,              y1=_pos,
                    xref='paper', yref='y',
                    line=dict(color=_minor_tick_color, width=0.7),
                    layer='above',
                )
            _pos = round(_pos + y_minor_dtick, 10)  # round avoids float drift

    # ── Right-side legend table (mirrors matplotlib _create_legend) ───────────
    #
    # All sizing values come from config (aesthetics.json -> per-chart merge).
    #
    wrap_w      = rc.get('legend_wrap_width', 28)
    # legend_w_px already computed above
    all_configs = config.get_all_series_configs()

    lines_html = []

    # Series rows: colored swatch + name
    for sc in all_configs:
        sname  = sc.get('name', 'Series')
        scolor = sc.get('line_color', '#1f77b4')
        lines_html.append(
            f'<span style="color:{scolor}">━━</span>  <b>{sname}</b>'
        )

    # Separator
    lines_html.append('<span style="color:#cccccc">──────────────────────</span>')

    # Task rows (deduplicated)
    seen_ids: Dict[str, bool] = {}
    for task in tasks:
        key = task.display_id
        if key in seen_ids:
            continue
        seen_ids[key] = True

        if gantt_config and gantt_config.is_loaded():
            t_color = gantt_config.get_color_for_test_id(task.test_id)
        else:
            t_color = task_colors.get(task.test_id, '#333333')

        wrapped_desc = _textwrap.wrap(task.description or '', wrap_w) or ['']
        desc_html    = '<br>'.join(wrapped_desc)
        lines_html.append(
            f'<b><span style="color:{t_color}">{task.display_id}</span></b>  {desc_html}'
        )

    legend_text = '<br>'.join(lines_html)

    _fig_w = width if width else 1200
    legend_w_px = max(200, int((1.0 - _right) * _fig_w) - 60)

    fig.add_annotation(
        x=leg_x, y=leg_y,
        xref='paper', yref='paper',
        xanchor='left', yanchor='top',
        text=legend_text,
        showarrow=False,
        align='left',
        font=dict(size=label_fs, family=font_family, color='#1a1a1a'),
        bgcolor='rgba(255,255,255,0.92)',
        bordercolor='rgba(0,0,0,0)',
        borderwidth=0,
        borderpad=8,
        width=legend_w_px,
    )

    return fig
