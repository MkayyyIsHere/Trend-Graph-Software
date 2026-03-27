"""1_app/config_manager_callbacks.py — All callbacks for the ⚙️ Config Manager tab."""

import json
import os
import re

from dash import Input, Output, State, ctx, html, no_update, ALL, MATCH
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from app.config_manager_layout import (
    COLOUR_PALETTES, CFG_TYPE_SERIES, CFG_TYPE_GANTT,
    _series_row, _gantt_color_row, _palette_color_row,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _list_json_files(folder: str) -> list[str]:
    """Return sorted list of .json filenames in *folder*."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(".json"))


def _safe_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_color(hex_val: str, fallback: str = "#000000") -> str:
    if hex_val and re.match(r"^#[0-9a-fA-F]{6}$", hex_val.strip()):
        return hex_val.strip()
    return fallback


# ── Series config helpers ─────────────────────────────────────────────────────

def _build_config_from_form(
    filename, description, usage,
    series_names, series_vcols, series_kws, series_alphas,
    series_color_hexes, series_linewidths, series_linestyles, series_markers,
    chart_title, bg_hex, res_w, res_h, dpi,
    x_label, y_label, y_min, y_max, x_min, x_max,
    grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
    sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy, sp_lgw,
    r_font_scale, r_lw_scale, r_title_fs, r_axis_fs, r_tick_fs, r_legend_fs,
    r_legend_ff, r_pad_top, r_sep_above, r_sep_below, r_gap_slots,
) -> dict:
    n_series = len(series_names) if series_names else 0
    series = []
    for i in range(n_series):
        kw_raw   = series_kws[i] if series_kws and i < len(series_kws) else ""
        keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
        series.append({
            "name":                  (series_names[i]    if series_names    else ""),
            "value_column":          (series_vcols[i]    if series_vcols    else ""),
            "value_column_keywords": keywords,
            "line_color":            _parse_color(series_color_hexes[i] if series_color_hexes else "#1f77b4"),
            "linewidth":             _safe_float(series_linewidths[i]   if series_linewidths  else 1.5, 1.5),
            "linestyle":             (series_linestyles[i] if series_linestyles else "-"),
            "alpha":                 _safe_float(series_alphas[i]       if series_alphas      else 0.65, 0.65),
            "marker":                (series_markers[i]   if series_markers    else "none"),
        })

    cfg = {
        "_description": description or "",
        "_usage":       usage or "",
        "series": series,
        "chart": {
            "title":            chart_title or "",
            "resolution_px":    [_safe_int(res_w, 2560), _safe_int(res_h, 1440)],
            "dpi":              _safe_int(dpi, 96),
            "background_color": _parse_color(bg_hex, "#ffffff"),
        },
        "axis": {
            "x_label": x_label or "",
            "y_label": y_label or "",
        },
        "grid": {
            "visible":   grid_visible == "true",
            "axis":      grid_axis or "both",
            "linestyle": grid_ls or "-",
            "alpha":     _safe_float(grid_alpha, 0.3),
            "color":     _parse_color(grid_color_hex, "#505050"),
            "gridwidth": _safe_float(grid_width, 1),
        },
        "subplot_params": {
            "left":            _safe_float(sp_left,   0.03),
            "right":           _safe_float(sp_right,  0.92),
            "top":             _safe_float(sp_top,    0.95),
            "bottom":          _safe_float(sp_bottom, 0.06),
            "legend_x":        _safe_float(sp_lgx,    0.92),
            "legend_y":        _safe_float(sp_lgy,    0.83),
            "legend_width_px": _safe_int(sp_lgw,      500),
        },
        "responsive": {
            "font_scale_factor":        _safe_float(r_font_scale, 1.0),
            "linewidth_scale_factor":   _safe_float(r_lw_scale,   1.0),
            "title_fontsize_base":      _safe_int(r_title_fs,     20),
            "axis_label_fontsize_base": _safe_int(r_axis_fs,      15),
            "tick_fontsize_base":       _safe_int(r_tick_fs,      12),
            "legend_fontsize_base":     _safe_int(r_legend_fs,    13),
            "legend_font_family":       r_legend_ff or "sans-serif",
            "legend_pad_top":           _safe_float(r_pad_top,    0.5),
            "legend_pad_sep_above":     _safe_float(r_sep_above,  0.4),
            "legend_pad_sep_below":     _safe_float(r_sep_below,  0.4),
            "legend_gap_slots":         _safe_float(r_gap_slots,  0.5),
        },
    }

    if y_min not in (None, ""):  cfg["axis"]["y_min"] = _safe_float(y_min)
    if y_max not in (None, ""):  cfg["axis"]["y_max"] = _safe_float(y_max)
    if x_min not in (None, ""):  cfg["axis"]["x_min"] = str(x_min)
    if x_max not in (None, ""):  cfg["axis"]["x_max"] = str(x_max)

    return cfg


def _populate_form_from_config(cfg: dict):
    series_list = cfg.get("series", [])
    if not isinstance(series_list, list):
        series_list = [series_list]

    rows  = [_series_row(i, s) for i, s in enumerate(series_list)]
    chart = cfg.get("chart", {})
    axis  = cfg.get("axis",  {})
    grid  = cfg.get("grid",  {})
    sp    = cfg.get("subplot_params", {})
    resp  = cfg.get("responsive", {})
    res   = chart.get("resolution_px", [2560, 1440])

    return rows, len(series_list), {
        "description":  cfg.get("_description", ""),
        "usage":        cfg.get("_usage", ""),
        "chart_title":  chart.get("title", ""),
        "bg_hex":       chart.get("background_color", "#ffffff"),
        "res_w":        res[0] if len(res) > 0 else 2560,
        "res_h":        res[1] if len(res) > 1 else 1440,
        "dpi":          chart.get("dpi", 96),
        "x_label":      axis.get("x_label", ""),
        "y_label":      axis.get("y_label", ""),
        "y_min":        axis.get("y_min", ""),
        "y_max":        axis.get("y_max", ""),
        "x_min":        axis.get("x_min", ""),
        "x_max":        axis.get("x_max", ""),
        "grid_visible": "true" if grid.get("visible", True) else "false",
        "grid_axis":    grid.get("axis", "both"),
        "grid_ls":      grid.get("linestyle", "-"),
        "grid_alpha":   grid.get("alpha", 0.3),
        "grid_width":   grid.get("gridwidth", 1),
        "grid_color":   grid.get("color", "#505050"),
        "sp_left":      sp.get("left",   0.03),
        "sp_right":     sp.get("right",  0.92),
        "sp_top":       sp.get("top",    0.95),
        "sp_bottom":    sp.get("bottom", 0.06),
        "sp_lgx":       sp.get("legend_x", 0.92),
        "sp_lgy":       sp.get("legend_y", 0.83),
        "sp_lgw":       sp.get("legend_width_px", 500),
        "r_font_scale": resp.get("font_scale_factor", 1.0),
        "r_lw_scale":   resp.get("linewidth_scale_factor", 1.0),
        "r_title_fs":   resp.get("title_fontsize_base", 20),
        "r_axis_fs":    resp.get("axis_label_fontsize_base", 15),
        "r_tick_fs":    resp.get("tick_fontsize_base", 12),
        "r_legend_fs":  resp.get("legend_fontsize_base", 13),
        "r_legend_ff":  resp.get("legend_font_family", "sans-serif"),
        "r_pad_top":    resp.get("legend_pad_top", 0.5),
        "r_sep_above":  resp.get("legend_pad_sep_above", 0.4),
        "r_sep_below":  resp.get("legend_pad_sep_below", 0.4),
        "r_gap_slots":  resp.get("legend_gap_slots", 0.5),
    }


# ── Gantt config helpers ──────────────────────────────────────────────────────

def _detect_config_type(cfg: dict) -> str:
    """Return CFG_TYPE_GANTT if JSON is a gantt/event config, else CFG_TYPE_SERIES."""
    if "gantt" in cfg or "gantt_colors" in cfg:
        return CFG_TYPE_GANTT
    return CFG_TYPE_SERIES


def _build_gantt_from_form(
    filename, description, usage,
    bar_alpha, bar_height, edge_hex, edge_width,
    test_ids, color_hexes,
    palette_hexes,
) -> dict:
    """Build a gantt config dict from form values."""
    gantt_colors = {}
    n_ids = len(test_ids) if test_ids else 0
    for i in range(n_ids):
        tid = (test_ids[i] or "").strip()
        if tid:
            gantt_colors[tid] = _parse_color(
                color_hexes[i] if color_hexes and i < len(color_hexes) else "#808080",
                "#808080",
            )

    palette = [
        _parse_color(c, "#1f77b4")
        for c in (palette_hexes or [])
        if c
    ]
    if not palette:
        palette = ["#1f77b4"]

    gantt_colors["default_palette"] = palette

    return {
        "_description": description or "",
        "_usage": usage or "",
        "gantt": {
            "bar_alpha":        _safe_float(bar_alpha, 0.3),
            "bar_height_ratio": _safe_float(bar_height, 1.0),
            "edge_color":       _parse_color(edge_hex, "#000000"),
            "edge_width":       _safe_float(edge_width, 0.2),
        },
        "gantt_colors": gantt_colors,
    }


def _populate_gantt_form(cfg: dict):
    """Extract gantt form values from a gantt config dict."""
    gantt  = cfg.get("gantt", {})
    colors = cfg.get("gantt_colors", {})
    palette = colors.get("default_palette", ["#1f77b4"])

    # Build color rows — skip meta / palette keys
    skip = {"_description", "_default_palette_info", "default_palette"}
    color_rows = []
    for k, v in colors.items():
        if k in skip or k.startswith("_"):
            continue
        color_rows.append(_gantt_color_row(len(color_rows), k, v))

    palette_rows = [_palette_color_row(i, c) for i, c in enumerate(palette)]

    # Normalise edge_color to hex for the colour swatch
    edge_color = gantt.get("edge_color", "black")
    named_to_hex = {
        "black": "#000000", "white": "#ffffff",
        "gray":  "#808080", "grey":  "#808080",
        "red":   "#ff0000", "blue":  "#0000ff",
    }
    if isinstance(edge_color, str):
        edge_hex = named_to_hex.get(edge_color.lower(), edge_color)
        if not re.match(r"^#[0-9a-fA-F]{6}$", edge_hex):
            edge_hex = "#000000"
    else:
        edge_hex = "#000000"

    return {
        "bar_alpha":    gantt.get("bar_alpha", 0.3),
        "bar_height":   gantt.get("bar_height_ratio", 1.0),
        "edge_hex":     edge_hex,
        "edge_width":   gantt.get("edge_width", 0.2),
        "color_rows":   color_rows,
        "n_colors":     len(color_rows),
        "palette_rows": palette_rows,
        "n_palette":    len(palette_rows),
    }


# ── File list renderer ────────────────────────────────────────────────────────

def _render_file_list(files: list[str], selected: str | None) -> list:
    from backend.batch_profile import BATCH_PROFILE_FILENAME
    if not files:
        return [html.P("No JSON files found in this folder.",
                       className="text-muted small mb-0")]
    items = []
    for f in files:
        if f == BATCH_PROFILE_FILENAME:
            # Show as read-only — not selectable, just informational
            items.append(
                dbc.ListGroupItem(
                    html.Div([
                        html.Span("🔒 ", style={"fontSize": "13px"}),
                        html.Span(f, className="small text-muted"),
                        dbc.Badge(
                            "read-only · managed by Batch Profile",
                            color="warning", text_color="dark",
                            className="ms-2",
                            style={"fontSize": "10px"},
                        ),
                    ]),
                    disabled=True,
                    style={"padding": "6px 12px", "opacity": "0.65",
                           "cursor": "not-allowed"},
                )
            )
        else:
            items.append(
                dbc.ListGroupItem(
                    html.Div([
                        html.Span("📄 ", style={"fontSize": "13px"}),
                        html.Span(f, className="small"),
                    ]),
                    id={"type": "cfgmgr-file-item", "index": f},
                    action=True,
                    active=(f == selected),
                    style={"cursor": "pointer", "padding": "6px 12px"},
                    n_clicks=0,
                )
            )
    return [dbc.ListGroup(items, flush=True)]


# ── Registration ──────────────────────────────────────────────────────────────

def register_config_manager_callbacks(app, state):
    """Register all Config Manager callbacks on *1_app*."""

    # ── Browse button → Flask folder-picker endpoint (clientside) ───────
    app.clientside_callback(
        """
        function(n) {
            if (!n) return window.dash_clientside.no_update;
            return fetch('/api/pick-folder?title=Select%20Config%20Folder')
                .then(r => r.json())
                .then(d => d.path || window.dash_clientside.no_update)
                .catch(() => window.dash_clientside.no_update);
        }
        """,
        Output("cfgmgr-folder-path", "value", allow_duplicate=True),
        Input("btn-cfgmgr-browse",   "n_clicks"),
        prevent_initial_call=True,
    )

    # ── Drop any file from folder → extract folder path ──────────────────
    @app.callback(
        Output("cfgmgr-folder-path", "value", allow_duplicate=True),
        Input("upload-cfgmgr-folder", "filename"),
        State("cfgmgr-folder-path",   "value"),
        prevent_initial_call=True,
    )
    def cfgmgr_folder_drop(filename, current):
        if not filename:
            raise PreventUpdate
        bases = ([os.path.dirname(current)] if current else []) + [os.getcwd()]
        for base in bases:
            candidate = os.path.join(base, filename)
            if os.path.isfile(candidate):
                return os.path.dirname(os.path.abspath(candidate))
        return os.getcwd()

    # ── Refresh file list ─────────────────────────────────────────────────
    @app.callback(
        Output("cfgmgr-file-list",     "children"),
        Output("cfgmgr-folder-status", "children"),
        Output("btn-cfgmgr-edit",      "disabled"),
        Output("btn-cfgmgr-clone",     "disabled"),
        Output("btn-cfgmgr-delete",    "disabled"),
        Input("btn-cfgmgr-refresh",    "n_clicks"),
        Input("cfgmgr-folder-path",    "value"),
        State("store-cfgmgr-selected", "data"),
        prevent_initial_call=True,
    )
    def refresh_file_list(_, folder, selected):
        if not folder or not folder.strip():
            return (
                [html.P("Enter a folder path above and click Refresh.",
                        className="text-muted small")],
                "", True, True, True,
            )
        folder = folder.strip()
        if not os.path.isdir(folder):
            return (
                [html.P("Folder not found.", className="text-danger small")],
                dbc.Alert(f"❌ Not a valid directory: {folder}",
                          color="danger", className="py-1 mb-0"),
                True, True, True,
            )
        files = _list_json_files(folder)
        if selected not in files:
            selected = None
        status = dbc.Alert(
            f"✓ {len(files)} JSON file(s) in {folder}",
            color="success", className="py-1 mb-0",
        )
        has_sel = selected is not None
        return (
            _render_file_list(files, selected),
            status,
            not has_sel, not has_sel, not has_sel,
        )

    # ── Click a file item → select it ────────────────────────────────────
    @app.callback(
        Output("store-cfgmgr-selected", "data"),
        Output("btn-cfgmgr-edit",       "disabled", allow_duplicate=True),
        Output("btn-cfgmgr-clone",      "disabled", allow_duplicate=True),
        Output("btn-cfgmgr-delete",     "disabled", allow_duplicate=True),
        Input({"type": "cfgmgr-file-item", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def select_file(n_clicks_list):
        if not any(n_clicks_list):
            raise PreventUpdate
        triggered = ctx.triggered_id
        if not triggered:
            raise PreventUpdate
        return triggered["index"], False, False, False

    # ── Highlight selected item ───────────────────────────────────────────
    @app.callback(
        Output({"type": "cfgmgr-file-item", "index": ALL}, "active"),
        Input("store-cfgmgr-selected", "data"),
        State({"type": "cfgmgr-file-item", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def highlight_selected(selected, ids):
        return [item["index"] == selected for item in ids]

    # ── Open editor: New / Edit / Clone ──────────────────────────────────
    @app.callback(
        Output("cfg-editor-modal",             "is_open",  allow_duplicate=True),
        Output("cfg-editor-title",             "children"),
        Output("store-cfgmgr-edit-mode",       "data"),
        Output("cfg-filename",                 "value"),
        Output("cfg-description",              "value"),
        Output("cfg-usage",                    "value"),
        # Series-data section
        Output("cfg-series-container",         "children"),
        Output("store-series-count",           "data"),
        Output("cfg-chart-title",              "value"),
        Output("cfg-bg-color-swatch",          "value"),
        Output("cfg-bg-color-hex",             "value"),
        Output("cfg-res-w",                    "value"),
        Output("cfg-res-h",                    "value"),
        Output("cfg-dpi",                      "value"),
        Output("cfg-x-label",                  "value"),
        Output("cfg-y-label",                  "value"),
        Output("cfg-y-min",                    "value"),
        Output("cfg-y-max",                    "value"),
        Output("cfg-x-min",                    "value"),
        Output("cfg-x-max",                    "value"),
        Output("cfg-grid-visible",             "value"),
        Output("cfg-grid-axis",               "value"),
        Output("cfg-grid-linestyle",           "value"),
        Output("cfg-grid-alpha",               "value"),
        Output("cfg-grid-width",               "value"),
        Output("cfg-grid-color-swatch",        "value"),
        Output("cfg-grid-color-hex",           "value"),
        Output("cfg-sp-left",                  "value"),
        Output("cfg-sp-right",                 "value"),
        Output("cfg-sp-top",                   "value"),
        Output("cfg-sp-bottom",                "value"),
        Output("cfg-sp-lgx",                   "value"),
        Output("cfg-sp-lgy",                   "value"),
        Output("cfg-sp-lgw",                   "value"),
        Output("cfg-r-font-scale",             "value"),
        Output("cfg-r-lw-scale",               "value"),
        Output("cfg-r-title-fs",               "value"),
        Output("cfg-r-axis-fs",                "value"),
        Output("cfg-r-tick-fs",                "value"),
        Output("cfg-r-legend-fs",              "value"),
        Output("cfg-r-legend-ff",              "value"),
        Output("cfg-r-pad-top",                "value"),
        Output("cfg-r-sep-above",              "value"),
        Output("cfg-r-sep-below",              "value"),
        Output("cfg-r-gap-slots",              "value"),
        # Gantt section
        Output("cfg-gantt-bar-alpha",          "value"),
        Output("cfg-gantt-bar-height",         "value"),
        Output("cfg-gantt-edge-swatch",        "value"),
        Output("cfg-gantt-edge-hex",           "value"),
        Output("cfg-gantt-edge-width",         "value"),
        Output("cfg-gantt-colors-container",   "children"),
        Output("store-gantt-color-count",      "data"),
        Output("cfg-gantt-palette-container",  "children"),
        Output("store-gantt-palette-count",    "data"),
        # Collapse visibility + type badge
        Output("cfg-gantt-collapse",           "is_open"),
        Output("cfg-series-sections-collapse", "is_open"),
        Output("store-cfg-type",               "data"),
        Output("cfg-type-badge",               "children"),
        Output("cfg-save-status",              "children", allow_duplicate=True),
        Input("btn-cfgmgr-new",                "n_clicks"),
        Input("btn-cfgmgr-edit",               "n_clicks"),
        Input("btn-cfgmgr-clone",              "n_clicks"),
        State("store-cfgmgr-selected",         "data"),
        State("cfgmgr-folder-path",            "value"),
        prevent_initial_call=True,
    )
    def open_editor(n_new, n_edit, n_clone, selected, folder):
        trigger = ctx.triggered_id

        SERIES_DEFAULTS = (
            [_series_row(0)], 1,
            "", "#ffffff", "#ffffff",
            2560, 1440, 96,
            "", "",
            "", "", "", "",
            "true", "both", "-",
            0.3, 1, "#505050", "#505050",
            0.03, 0.92, 0.95, 0.06,
            0.92, 0.83, 500,
            1.0, 1.0, 20, 15, 12, 13,
            "sans-serif",
            0.5, 0.4, 0.4, 0.5,
        )
        GANTT_DEFAULTS = (
            0.3, 1.0, "#000000", "#000000", 0.2,
            [], 0,
            [], 0,
        )

        def _series_badge():
            return dbc.Badge("📈 Series Config", color="primary", className="fs-6")

        def _gantt_badge():
            return dbc.Badge("🎨 Gantt / Event Config", color="success", className="fs-6")

        BLANK = (
            True, "New Config", "new",
            "", "", "",
            *SERIES_DEFAULTS,
            *GANTT_DEFAULTS,
            False, True, CFG_TYPE_SERIES, _series_badge(), "",
        )

        if trigger == "btn-cfgmgr-new":
            return BLANK

        if not selected or not folder:
            raise PreventUpdate

        path = os.path.join(folder.strip(), selected)
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            raise PreventUpdate

        cfg_type = _detect_config_type(cfg)

        if trigger == "btn-cfgmgr-edit":
            mode  = "edit"
            title = f"Edit — {selected}"
            fname = selected
        else:
            mode  = "clone"
            title = f"Clone — {selected}"
            fname = ""

        if cfg_type == CFG_TYPE_GANTT:
            gv = _populate_gantt_form(cfg)
            return (
                True, title, mode,
                fname,
                cfg.get("_description", ""),
                cfg.get("_usage", ""),
                # Series sections — blank/defaults (will be collapsed)
                *SERIES_DEFAULTS,
                # Gantt section
                gv["bar_alpha"], gv["bar_height"],
                gv["edge_hex"], gv["edge_hex"], gv["edge_width"],
                gv["color_rows"], gv["n_colors"],
                gv["palette_rows"], gv["n_palette"],
                # Collapse states: gantt open, series closed
                True, False, CFG_TYPE_GANTT, _gantt_badge(), "",
            )

        # ── Series config ─────────────────────────────────────────────────
        rows, n_series, fv = _populate_form_from_config(cfg)
        return (
            True, title, mode,
            fname, fv["description"], fv["usage"],
            rows, n_series,
            fv["chart_title"],
            fv["bg_hex"], fv["bg_hex"],
            fv["res_w"], fv["res_h"], fv["dpi"],
            fv["x_label"], fv["y_label"],
            fv["y_min"], fv["y_max"], fv["x_min"], fv["x_max"],
            fv["grid_visible"], fv["grid_axis"], fv["grid_ls"],
            fv["grid_alpha"], fv["grid_width"],
            fv["grid_color"], fv["grid_color"],
            fv["sp_left"], fv["sp_right"], fv["sp_top"], fv["sp_bottom"],
            fv["sp_lgx"], fv["sp_lgy"], fv["sp_lgw"],
            fv["r_font_scale"], fv["r_lw_scale"],
            fv["r_title_fs"], fv["r_axis_fs"], fv["r_tick_fs"], fv["r_legend_fs"],
            fv["r_legend_ff"],
            fv["r_pad_top"], fv["r_sep_above"], fv["r_sep_below"], fv["r_gap_slots"],
            # Gantt section — blank/defaults (will be collapsed)
            *GANTT_DEFAULTS,
            # Collapse states: series open, gantt closed
            False, True, CFG_TYPE_SERIES, _series_badge(), "",
        )

    # ── Add series ────────────────────────────────────────────────────────
    @app.callback(
        Output("cfg-series-container", "children", allow_duplicate=True),
        Output("store-series-count",   "data",     allow_duplicate=True),
        Input("btn-add-series",        "n_clicks"),
        State("store-series-count",    "data"),
        State("cfg-series-container",  "children"),
        prevent_initial_call=True,
    )
    def add_series(_, count, current):
        count = count or 0
        return (current or []) + [_series_row(count)], count + 1

    # ── Remove series ─────────────────────────────────────────────────────
    @app.callback(
        Output("cfg-series-container", "children", allow_duplicate=True),
        Output("store-series-count",   "data",     allow_duplicate=True),
        Input({"type": "btn-remove-series", "index": ALL}, "n_clicks"),
        State("cfg-series-container",  "children"),
        State("store-series-count",    "data"),
        prevent_initial_call=True,
    )
    def remove_series(n_clicks_list, current, count):
        if not any(n for n in n_clicks_list if n):
            raise PreventUpdate
        triggered = ctx.triggered_id
        if triggered is None:
            raise PreventUpdate
        remove_idx = triggered["index"]
        new_rows = [
            r for r in (current or [])
            if not (isinstance(r, dict)
                    and r.get("props", {}).get("id") == f"series-card-{remove_idx}")
        ]
        return new_rows, max(0, (count or 1) - 1)

    # ── Add gantt Test ID colour row ──────────────────────────────────────
    @app.callback(
        Output("cfg-gantt-colors-container", "children", allow_duplicate=True),
        Output("store-gantt-color-count",    "data",     allow_duplicate=True),
        Input("btn-add-gantt-color",         "n_clicks"),
        State("store-gantt-color-count",     "data"),
        State("cfg-gantt-colors-container",  "children"),
        prevent_initial_call=True,
    )
    def add_gantt_color(_, count, current):
        count = count or 0
        return (current or []) + [_gantt_color_row(count)], count + 1

    # ── Remove gantt Test ID colour row ──────────────────────────────────
    @app.callback(
        Output("cfg-gantt-colors-container", "children", allow_duplicate=True),
        Output("store-gantt-color-count",    "data",     allow_duplicate=True),
        Input({"type": "btn-remove-gantt-color", "index": ALL}, "n_clicks"),
        State("cfg-gantt-colors-container",  "children"),
        State("store-gantt-color-count",     "data"),
        prevent_initial_call=True,
    )
    def remove_gantt_color(n_clicks_list, current, count):
        if not any(n for n in n_clicks_list if n):
            raise PreventUpdate
        triggered = ctx.triggered_id
        if triggered is None:
            raise PreventUpdate
        remove_idx = triggered["index"]
        new_rows = [
            r for r in (current or [])
            if not (isinstance(r, dict)
                    and r.get("props", {}).get("id") == f"gantt-color-card-{remove_idx}")
        ]
        return new_rows, max(0, (count or 1) - 1)

    # ── Add default palette colour row ────────────────────────────────────
    @app.callback(
        Output("cfg-gantt-palette-container", "children", allow_duplicate=True),
        Output("store-gantt-palette-count",   "data",     allow_duplicate=True),
        Input("btn-add-palette-color",        "n_clicks"),
        State("store-gantt-palette-count",    "data"),
        State("cfg-gantt-palette-container",  "children"),
        prevent_initial_call=True,
    )
    def add_palette_color(_, count, current):
        count = count or 0
        return (current or []) + [_palette_color_row(count)], count + 1

    # ── Remove default palette colour row ─────────────────────────────────
    @app.callback(
        Output("cfg-gantt-palette-container", "children", allow_duplicate=True),
        Output("store-gantt-palette-count",   "data",     allow_duplicate=True),
        Input({"type": "btn-remove-palette-color", "index": ALL}, "n_clicks"),
        State("cfg-gantt-palette-container",  "children"),
        State("store-gantt-palette-count",    "data"),
        prevent_initial_call=True,
    )
    def remove_palette_color(n_clicks_list, current, count):
        if not any(n for n in n_clicks_list if n):
            raise PreventUpdate
        triggered = ctx.triggered_id
        if triggered is None:
            raise PreventUpdate
        remove_idx = triggered["index"]
        new_rows = [
            r for r in (current or [])
            if not (isinstance(r, dict)
                    and r.get("props", {}).get("id") == f"gantt-palette-card-{remove_idx}")
        ]
        return new_rows, max(0, (count or 1) - 1)

    # ── Colour swatch ↔ hex sync (series) ────────────────────────────────
    app.clientside_callback(
        "function(v) { return v; }",
        Output({"type": "series-color-hex",    "index": MATCH}, "value"),
        Input( {"type": "series-color-swatch", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        """function(v) {
            if (!v) return window.dash_clientside.no_update;
            v = v.trim();
            return /^#[0-9a-fA-F]{6}$/.test(v) ? v : window.dash_clientside.no_update;
        }""",
        Output({"type": "series-color-swatch", "index": MATCH}, "value"),
        Input( {"type": "series-color-hex",    "index": MATCH}, "value"),
        prevent_initial_call=True,
    )

    # ── Colour swatch ↔ hex sync (gantt Test ID colours) ─────────────────
    app.clientside_callback(
        "function(v) { return v; }",
        Output({"type": "gantt-color-hex",    "index": MATCH}, "value"),
        Input( {"type": "gantt-color-swatch", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        """function(v) {
            if (!v) return window.dash_clientside.no_update;
            v = v.trim();
            return /^#[0-9a-fA-F]{6}$/.test(v) ? v : window.dash_clientside.no_update;
        }""",
        Output({"type": "gantt-color-swatch", "index": MATCH}, "value"),
        Input( {"type": "gantt-color-hex",    "index": MATCH}, "value"),
        prevent_initial_call=True,
    )

    # ── Colour swatch ↔ hex sync (gantt palette colours) ─────────────────
    app.clientside_callback(
        "function(v) { return v; }",
        Output({"type": "gantt-palette-hex",    "index": MATCH}, "value"),
        Input( {"type": "gantt-palette-swatch", "index": MATCH}, "value"),
        prevent_initial_call=True,
    )
    app.clientside_callback(
        """function(v) {
            if (!v) return window.dash_clientside.no_update;
            v = v.trim();
            return /^#[0-9a-fA-F]{6}$/.test(v) ? v : window.dash_clientside.no_update;
        }""",
        Output({"type": "gantt-palette-swatch", "index": MATCH}, "value"),
        Input( {"type": "gantt-palette-hex",    "index": MATCH}, "value"),
        prevent_initial_call=True,
    )

    # ── Colour swatch ↔ hex sync (bg, grid, gantt edge) ──────────────────
    for swatch_id, hex_id in [
        ("cfg-bg-color-swatch",   "cfg-bg-color-hex"),
        ("cfg-grid-color-swatch", "cfg-grid-color-hex"),
        ("cfg-gantt-edge-swatch", "cfg-gantt-edge-hex"),
    ]:
        app.clientside_callback(
            "function(v) { return v; }",
            Output(hex_id,    "value", allow_duplicate=True),
            Input( swatch_id, "value"),
            prevent_initial_call=True,
        )
        app.clientside_callback(
            """function(v) {
                if (!v) return window.dash_clientside.no_update;
                v = v.trim();
                return /^#[0-9a-fA-F]{6}$/.test(v) ? v : window.dash_clientside.no_update;
            }""",
            Output(swatch_id, "value", allow_duplicate=True),
            Input( hex_id,    "value"),
            prevent_initial_call=True,
        )

    # ── Apply colour palette ──────────────────────────────────────────────
    @app.callback(
        Output({"type": "series-color-hex",    "index": ALL}, "value", allow_duplicate=True),
        Output({"type": "series-color-swatch", "index": ALL}, "value", allow_duplicate=True),
        Input("btn-apply-palette",  "n_clicks"),
        State("cfg-palette-select", "value"),
        State({"type": "series-color-hex", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def apply_palette(_, palette_name, ids):
        if not palette_name or palette_name not in COLOUR_PALETTES:
            raise PreventUpdate
        palette = COLOUR_PALETTES[palette_name]
        colors  = [palette[i % len(palette)] for i in range(len(ids))]
        return colors, colors

    # ── Cancel editor ─────────────────────────────────────────────────────
    @app.callback(
        Output("cfg-editor-modal", "is_open", allow_duplicate=True),
        Input("btn-cfg-cancel",    "n_clicks"),
        prevent_initial_call=True,
    )
    def close_editor(_):
        return False

    # ── Save ──────────────────────────────────────────────────────────────
    @app.callback(
        Output("cfg-save-status",       "children",  allow_duplicate=True),
        Output("cfg-editor-modal",      "is_open",   allow_duplicate=True),
        Output("cfgmgr-file-list",      "children",  allow_duplicate=True),
        Output("cfgmgr-action-status",  "children"),
        Output("store-cfgmgr-selected", "data",      allow_duplicate=True),
        Input("btn-cfg-save", "n_clicks"),
        State("store-cfgmgr-edit-mode", "data"),
        State("store-cfg-type",         "data"),
        State("cfgmgr-folder-path",     "value"),
        State("cfg-filename",           "value"),
        State("cfg-description",        "value"),
        State("cfg-usage",              "value"),
        # Series states
        State({"type": "series-name",       "index": ALL}, "value"),
        State({"type": "series-value-col",  "index": ALL}, "value"),
        State({"type": "series-keywords",   "index": ALL}, "value"),
        State({"type": "series-alpha",      "index": ALL}, "value"),
        State({"type": "series-color-hex",  "index": ALL}, "value"),
        State({"type": "series-linewidth",  "index": ALL}, "value"),
        State({"type": "series-linestyle",  "index": ALL}, "value"),
        State({"type": "series-marker",     "index": ALL}, "value"),
        State("cfg-chart-title",    "value"),
        State("cfg-bg-color-hex",   "value"),
        State("cfg-res-w",          "value"),
        State("cfg-res-h",          "value"),
        State("cfg-dpi",            "value"),
        State("cfg-x-label",        "value"),
        State("cfg-y-label",        "value"),
        State("cfg-y-min",          "value"),
        State("cfg-y-max",          "value"),
        State("cfg-x-min",          "value"),
        State("cfg-x-max",          "value"),
        State("cfg-grid-visible",   "value"),
        State("cfg-grid-axis",      "value"),
        State("cfg-grid-linestyle", "value"),
        State("cfg-grid-alpha",     "value"),
        State("cfg-grid-width",     "value"),
        State("cfg-grid-color-hex", "value"),
        State("cfg-sp-left",        "value"),
        State("cfg-sp-right",       "value"),
        State("cfg-sp-top",         "value"),
        State("cfg-sp-bottom",      "value"),
        State("cfg-sp-lgx",         "value"),
        State("cfg-sp-lgy",         "value"),
        State("cfg-sp-lgw",         "value"),
        State("cfg-r-font-scale",   "value"),
        State("cfg-r-lw-scale",     "value"),
        State("cfg-r-title-fs",     "value"),
        State("cfg-r-axis-fs",      "value"),
        State("cfg-r-tick-fs",      "value"),
        State("cfg-r-legend-fs",    "value"),
        State("cfg-r-legend-ff",    "value"),
        State("cfg-r-pad-top",      "value"),
        State("cfg-r-sep-above",    "value"),
        State("cfg-r-sep-below",    "value"),
        State("cfg-r-gap-slots",    "value"),
        # Gantt states
        State("cfg-gantt-bar-alpha",  "value"),
        State("cfg-gantt-bar-height", "value"),
        State("cfg-gantt-edge-hex",   "value"),
        State("cfg-gantt-edge-width", "value"),
        State({"type": "gantt-test-id",     "index": ALL}, "value"),
        State({"type": "gantt-color-hex",   "index": ALL}, "value"),
        State({"type": "gantt-palette-hex", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def save_config(
        _, mode, cfg_type, folder, filename,
        description, usage,
        series_names, series_vcols, series_kws, series_alphas,
        series_color_hexes, series_linewidths, series_linestyles, series_markers,
        chart_title, bg_hex, res_w, res_h, dpi,
        x_label, y_label, y_min, y_max, x_min, x_max,
        grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
        sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy, sp_lgw,
        r_font_scale, r_lw_scale, r_title_fs, r_axis_fs, r_tick_fs, r_legend_fs,
        r_legend_ff, r_pad_top, r_sep_above, r_sep_below, r_gap_slots,
        gantt_bar_alpha, gantt_bar_height, gantt_edge_hex, gantt_edge_width,
        gantt_test_ids, gantt_color_hexes, gantt_palette_hexes,
    ):
        ERR = lambda msg: (  # noqa: E731
            dbc.Alert(msg, color="danger", className="py-1"),
            True, no_update, no_update, no_update,
        )

        if not folder or not os.path.isdir(folder.strip()):
            return ERR("❌ Invalid config folder.")
        if not filename or not filename.strip():
            return ERR("❌ Please enter a filename.")

        fname = filename.strip()
        if not fname.lower().endswith(".json"):
            fname += ".json"
        fname    = re.sub(r'[<>:"/\\|?*]', "_", fname)
        out_path = os.path.join(folder.strip(), fname)

        if cfg_type == CFG_TYPE_GANTT:
            cfg = _build_gantt_from_form(
                fname, description, usage,
                gantt_bar_alpha, gantt_bar_height, gantt_edge_hex, gantt_edge_width,
                gantt_test_ids, gantt_color_hexes,
                gantt_palette_hexes,
            )
            n_ids   = len([k for k in cfg.get("gantt_colors", {})
                           if not k.startswith("_") and k != "default_palette"])
            summary = f"✓ Saved gantt config: {fname}  ({n_ids} Test IDs)"
        else:
            cfg = _build_config_from_form(
                fname, description, usage,
                series_names, series_vcols, series_kws, series_alphas,
                series_color_hexes, series_linewidths, series_linestyles, series_markers,
                chart_title, bg_hex, res_w, res_h, dpi,
                x_label, y_label, y_min, y_max, x_min, x_max,
                grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
                sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy, sp_lgw,
                r_font_scale, r_lw_scale, r_title_fs, r_axis_fs, r_tick_fs, r_legend_fs,
                r_legend_ff, r_pad_top, r_sep_above, r_sep_below, r_gap_slots,
            )
            summary = f"✓ Saved: {fname}  ({len(cfg.get('series', []))} series)"

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return ERR(f"❌ Error saving: {e}")

        files     = _list_json_files(folder.strip())
        file_list = _render_file_list(files, fname)
        action    = dbc.Alert(summary, color="success", className="py-1 mb-0")
        return "", False, file_list, action, fname

    # ── Delete — open confirm ─────────────────────────────────────────────
    @app.callback(
        Output("cfg-confirm-delete-modal", "is_open", allow_duplicate=True),
        Output("cfg-delete-confirm-text",  "children"),
        Input("btn-cfgmgr-delete",         "n_clicks"),
        State("store-cfgmgr-selected",     "data"),
        prevent_initial_call=True,
    )
    def open_delete_confirm(_, selected):
        if not selected:
            raise PreventUpdate
        return True, f"Are you sure you want to permanently delete \"{selected}\"?"

    # ── Delete — cancel ───────────────────────────────────────────────────
    @app.callback(
        Output("cfg-confirm-delete-modal", "is_open", allow_duplicate=True),
        Input("btn-cfg-cancel-delete",     "n_clicks"),
        prevent_initial_call=True,
    )
    def cancel_delete(_):
        return False

    # ── Delete — confirm ──────────────────────────────────────────────────
    @app.callback(
        Output("cfg-confirm-delete-modal", "is_open",  allow_duplicate=True),
        Output("cfgmgr-file-list",         "children", allow_duplicate=True),
        Output("cfgmgr-action-status",     "children", allow_duplicate=True),
        Output("store-cfgmgr-selected",    "data",     allow_duplicate=True),
        Output("btn-cfgmgr-edit",          "disabled", allow_duplicate=True),
        Output("btn-cfgmgr-clone",         "disabled", allow_duplicate=True),
        Output("btn-cfgmgr-delete",        "disabled", allow_duplicate=True),
        Input("btn-cfg-confirm-delete",    "n_clicks"),
        State("store-cfgmgr-selected",     "data"),
        State("cfgmgr-folder-path",        "value"),
        prevent_initial_call=True,
    )
    def confirm_delete(_, selected, folder):
        if not selected or not folder:
            raise PreventUpdate
        path = os.path.join(folder.strip(), selected)
        try:
            os.remove(path)
        except Exception as e:
            status = dbc.Alert(f"❌ Delete failed: {e}",
                               color="danger", className="py-1 mb-0")
            return False, no_update, status, no_update, no_update, no_update, no_update

        files     = _list_json_files(folder.strip())
        file_list = _render_file_list(files, None)
        status    = dbc.Alert(f"🗑️ Deleted: {selected}",
                              color="warning", className="py-1 mb-0")
        return False, file_list, status, None, True, True, True