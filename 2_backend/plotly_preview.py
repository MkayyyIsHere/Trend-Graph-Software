# =============================================================================
# PLOTLY PREVIEW BUILDER  (faithful translation of the Matplotlib chart)
# =============================================================================

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
    if y_min_cfg is not None and y_max_cfg is not None:
        data_min, data_max = float(y_min_cfg), float(y_max_cfg)
    elif flat_points:
        vals = [dp.value for dp in flat_points]
        data_min, data_max = min(vals), max(vals)
    else:
        data_min, data_max = 0.0, 1.0
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

        first = True
        for segment in segments:
            fig.add_trace(go.Scatter(
                x=[dp.timestamp for dp in segment],
                y=[dp.value     for dp in segment],
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
            xref='x', yref='paper',
            line=dict(color=edge_rgba, width=1),
            layer='below',
        )
        # Right edge only
        fig.add_shape(
            type='line',
            x0=task.end_time, x1=task.end_time,
            y0=0, y1=1,
            xref='x', yref='paper',
            line=dict(color=edge_rgba, width=1),
            layer='below',
        )

    # ── Collision-free label rows (mirrors matplotlib algorithm) ─────────────
    #
    # We work in data-units for Y, datetime for X.
    # Rows stack downward from (data_max - 3 % gap).
    # X-collision is checked in timestamp seconds (no renderer needed in Plotly).
    #
    label_fs   = rc.get('legend_fontsize_base', 10) * 0.85
    # Estimate row height as a fraction of data range (same cap logic as mpl)
    _t         = max(0.0, min(1.0, (data_range - 1.0) / (5000.0 - 1.0)))
    cap_pct    = 0.06 * (1 - _t) + 0.03 * _t
    row_step   = data_range * cap_pct

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
            font=dict(size=label_fs, color=color, family='sans-serif'),
            xanchor='left', yanchor='bottom',
            bgcolor='rgba(255,255,255,0.85)',
            bordercolor=color,
            borderwidth=0.8,
            borderpad=2,
        )

    # ── Layout ────────────────────────────────────────────────────────────────
    y_range = None
    if y_min_cfg is not None and y_max_cfg is not None:
        y_range = [float(y_min_cfg), float(y_max_cfg)]
    elif flat_points:
        pad = data_range * 0.05
        y_range = [data_min - pad, data_max + pad]

    x_range = None
    if x_min_dt and x_max_dt:
        x_range = [x_min_dt, x_max_dt]

    fig.update_layout(
        title=dict(text=cc.get('title', 'Data Over Time with Events'),
                   font=dict(size=18), x=0.5),
        xaxis=dict(
            title=ac.get('x_label', 'Date & Time'),
            range=x_range,
            showgrid=True, gridcolor='rgba(80,80,80,0.25)',
            tickformat='%H:%M<br>%b %d',
            showspikes=True, spikemode='across', spikesnap='cursor',
            spikedash='solid', spikecolor='gray', spikethickness=1,
            showline=True, linecolor='rgba(80,80,80,0.8)', linewidth=1.5,
            ticks='outside', ticklen=6, tickwidth=1, tickcolor='rgba(80,80,80,0.8)',
            minor=dict(ticks='outside', ticklen=3, tickwidth=0.7, tickcolor='rgba(80,80,80,0.6)'),
        ),
        yaxis=dict(
            title=ac.get('y_label', 'Value'),
            range=y_range,
            showgrid=True, gridcolor='rgba(80,80,80,0.25)',
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        hovermode='x unified',
        # Legend is rebuilt below as annotations — hide the auto legend
        showlegend=True,
        legend=dict(
            orientation='v',
            x=1.02, xanchor='left',
            y=1.0,  yanchor='top',
            bgcolor='rgba(255,255,255,0.9)',
            bordercolor='rgba(0,0,0,0)',
            borderwidth=0,
            font=dict(size=label_fs),
            title=dict(text=''),
        ),
        margin=dict(l=70, r=320, t=70, b=80),
        # When explicit pixel dims are provided (batch export): fix the size
        # so kaleido renders at exactly the right resolution.
        # When no dims given (browser preview): autosize=True so the figure
        # fills its CSS container instead of overflowing the page.
        **(dict(width=width, height=height, autosize=False)
           if width and height else dict(autosize=True)),
    )

    # ── Right-side legend table (mirrors matplotlib _create_legend) ───────────
    #
    # We draw it as a paper-referenced annotation block at x=1.02, y=0..1.
    # Format:
    #   [color line]  Series Name
    #   ──────────────────────────
    #   TestID (bold)    Description
    #
    # Because Plotly annotations don't support mixed bold/normal in one block,
    # we use HTML tags with <b> inside the text string.
    #
    wrap_w    = rc.get('legend_wrap_width', 28)
    all_configs = config.get_all_series_configs()

    # Build the annotation text
    lines_html = []

    # Series rows: colored line indicator + name
    for sc in all_configs:
        sname = sc.get('name', 'Series')
        scolor = sc.get('line_color', '#1f77b4')
        # Unicode dash in color acts as swatch
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

        # Get color for this test id
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

    fig.add_annotation(
        x=1.02, y=1.0,
        xref='paper', yref='paper',
        xanchor='left', yanchor='top',
        text=legend_text,
        showarrow=False,
        align='left',
        font=dict(size=label_fs, family='monospace', color='#1a1a1a'),
        bgcolor='rgba(255,255,255,0.92)',
        bordercolor='rgba(0,0,0,0)',
        borderwidth=0,
        borderpad=8,
        width=280,
    )

    return fig