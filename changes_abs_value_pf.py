# =============================================================================
# SUMMARY OF CHANGES — Power Factor abs() plotting
# =============================================================================
#
# Three files were modified. Copy-paste the relevant sections into each file.
#
# WHAT CHANGED:
#   - Added "abs_value": true to each series in Power Factor.json
#   - chart_gen.py  → _plot_all_series() now reads abs_value flag per series
#   - chart_gen.py  → _plot_gantt_events() Gantt label placement uses abs values
#   - plotly_preview.py → series lines now apply abs() when flag is set
#   - plotly_preview.py → actual_data_min/max for label placement also abs-aware
#
# HOW IT WORKS:
#   Any series with "abs_value": true in its config block will have abs()
#   applied at plot time (both Matplotlib export and Plotly live preview).
#   Series without the flag are unaffected. To disable for a series, remove
#   the key or set it to false.
# =============================================================================


# -----------------------------------------------------------------------------
# 1.  5_configs/charts/Power Factor.json
#     Add "abs_value": true to each of the three series blocks.
# -----------------------------------------------------------------------------

POWER_FACTOR_JSON = """
{
  "_description": "Config for plotting 3-Phase Power Factor over time with Gantt events overlay.",
  "_usage": "Load via 'Browse Config...' in the GUI. Visual aesthetics (fonts, resolution, grid, legend) are inherited from aesthetics.json.",
  "series": [
    {
      "name": "PF Avg A",
      "value_column": "PfFwdRev_A_avg",
      "value_column_keywords": [
        "pffwdrev_a_avg"
      ],
      "line_color": "#000000",
      "linewidth": 1.5,
      "linestyle": "-",
      "alpha": 1.0,
      "marker": "none",
      "abs_value": true          <-- ADD THIS
    },
    {
      "name": "PF Avg B",
      "value_column": "PfFwdRev_B_avg",
      "value_column_keywords": [
        "pffwdrev_b_avg"
      ],
      "line_color": "#d62728",
      "linewidth": 1.5,
      "linestyle": "-",
      "alpha": 1.0,
      "marker": "none",
      "abs_value": true          <-- ADD THIS
    },
    {
      "name": "PF Avg C",
      "value_column": "PfFwdRev_C_avg",
      "value_column_keywords": [
        "pffwdrev_c_avg"
      ],
      "line_color": "#1f77b4",
      "linewidth": 1.5,
      "linestyle": "-",
      "alpha": 1.0,
      "marker": "none",
      "abs_value": true          <-- ADD THIS
    }
  ],
  ...
}
"""


# -----------------------------------------------------------------------------
# 2.  2_backend/chart_gen.py  —  _plot_all_series()
#     Replace the inner for-loop (around line 105) with this version.
# -----------------------------------------------------------------------------

# BEFORE:
#   for i, segment in enumerate(segments):
#       self.ax.plot(
#           [dp.timestamp for dp in segment],
#           [dp.value     for dp in segment],
#           color=color, linewidth=linewidth, linestyle=linestyle,
#           alpha=alpha, label=name if i == 0 else '',
#           marker='', markersize=0, zorder=3)

# AFTER:
def _plot_all_series_CHANGE(self, all_series_data):
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
        use_abs = sc.get('abs_value', False)                          # <-- NEW
        for i, segment in enumerate(segments):
            values = [abs(dp.value) if use_abs else dp.value          # <-- NEW
                      for dp in segment]                               # <-- NEW
            self.ax.plot(
                [dp.timestamp for dp in segment],
                values,                                                # <-- CHANGED (was [dp.value ...])
                color=color, linewidth=linewidth, linestyle=linestyle,
                alpha=alpha, label=name if i == 0 else '',
                marker='', markersize=0, zorder=3)
    self._log(f"Plotted {len(all_series_data)} series total")


# -----------------------------------------------------------------------------
# 3.  2_backend/chart_gen.py  —  _plot_gantt_events()
#     Replace the vals / actual_data_min/max block (around line 153).
# -----------------------------------------------------------------------------

# BEFORE:
#   vals = [dp.value for dp in data_points]
#   actual_data_min, actual_data_max = min(vals), max(vals)

# AFTER:
#   all_cfgs_gantt = self.config.get_all_series_configs()
#   vals = []
#   for i, dp in enumerate(data_points):
#       vals.append(dp.value)
#   # Apply abs for any series that has abs_value=True
#   if any(sc.get('abs_value', False) for sc in all_cfgs_gantt):
#       vals = [abs(v) for v in vals]
#   actual_data_min, actual_data_max = min(vals), max(vals)


# -----------------------------------------------------------------------------
# 4.  2_backend/plotly_preview.py  —  actual_data_min/max block (~line 52)
#     Replace the vals computation after flat_points is built.
# -----------------------------------------------------------------------------

# BEFORE:
#   if flat_points:
#       vals = [dp.value for dp in flat_points]
#       actual_data_min, actual_data_max = min(vals), max(vals)

# AFTER:
#   if flat_points:
#       abs_flags = {i: sc.get('abs_value', False) for i, sc in enumerate(all_cfg)}
#       vals = []
#       for idx, data_points in enumerate(all_series_data):
#           use_abs = abs_flags.get(idx, False)
#           for dp in data_points:
#               vals.append(abs(dp.value) if use_abs else dp.value)
#       actual_data_min, actual_data_max = min(vals), max(vals)


# -----------------------------------------------------------------------------
# 5.  2_backend/plotly_preview.py  —  series lines block (~line 84)
#     Replace the first=True / for segment loop with this version.
# -----------------------------------------------------------------------------

# BEFORE:
#   first = True
#   for segment in segments:
#       fig.add_trace(go.Scatter(
#           x=[dp.timestamp for dp in segment],
#           y=[dp.value     for dp in segment],
#           ...

# AFTER:
#   use_abs = sc.get('abs_value', False)       <-- NEW
#   first = True
#   for segment in segments:
#       values = [abs(dp.value) if use_abs else dp.value for dp in segment]  <-- NEW
#       fig.add_trace(go.Scatter(
#           x=[dp.timestamp for dp in segment],
#           y=values,                           <-- CHANGED (was [dp.value ...])
#           ...
