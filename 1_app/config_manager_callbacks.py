"""1_app/config_manager_callbacks.py — All callbacks for the ⚙️ Config Manager tab."""

import json
import os
import re

from dash import Input, Output, State, ctx, html, no_update, ALL, MATCH
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from app.config_manager_layout import (
    COLOUR_PALETTES, CFG_TYPE_SERIES, CFG_TYPE_GANTT, CFG_TYPE_AESTHETICS,
    _series_row, _gantt_color_row, _palette_color_row,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

# Filenames that are never shown in the chart file list
_AESTHETICS_FILENAME   = 'aesthetics.json'
_BATCH_PROFILE_FILENAME = 'batch_profile.json'
_RESERVED = {_AESTHETICS_FILENAME, _BATCH_PROFILE_FILENAME}


def _list_json_files(folder: str) -> list[str]:
    """Return sorted list of chart .json filenames in *folder* (reserved files excluded)."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(
        f for f in os.listdir(folder)
        if f.lower().endswith(".json") and f not in _RESERVED
    )


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
    chart_title,
    x_label, y_label, y_min, y_max, x_min, x_max,
) -> dict:
    """
    Build a slim per-chart config dict.
    Only unique-per-chart fields are written (series, title, axis).
    Aesthetic fields (fonts, grid, resolution, background) live in aesthetics.json.
    """
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
            "title": chart_title or "",
        },
        "axis": {
            "x_label": x_label or "",
            "y_label": y_label or "",
        },
    }

    if y_min not in (None, ""):  cfg["axis"]["y_min"] = _safe_float(y_min)
    if y_max not in (None, ""):  cfg["axis"]["y_max"] = _safe_float(y_max)
    if x_min not in (None, ""):  cfg["axis"]["x_min"] = str(x_min)
    if x_max not in (None, ""):  cfg["axis"]["x_max"] = str(x_max)

    return cfg


def _build_aesthetics_from_form(
    font_family, title_fs, axis_fs, tick_fs, legend_fs, font_scale,
    bg_color_hex,
    res_w, res_h, dpi,
    grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
    sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy,
    legend_width_px, legend_wrap_w,
    pad_top, pad_sep_above, pad_sep_below, gap_slots,
    lw_scale,
) -> dict:
    """Build the aesthetics.json dict from the aesthetics editor form."""
    return {
        "_description": "Master aesthetics config — single source of truth for all visual settings.",
        "_usage": "Loaded automatically before any per-chart config. Per-chart JSONs may override fields here, but a WARNING will be logged.",
        "font": {
            "family":          font_family or "sans-serif",
            "title_size":      _safe_int(title_fs,  20),
            "axis_label_size": _safe_int(axis_fs,   15),
            "tick_size":       _safe_int(tick_fs,   12),
            "legend_size":     _safe_int(legend_fs, 13),
            "scale_factor":    _safe_float(font_scale, 1.0),
        },
        "legend": {
            "width_px":      _safe_int(legend_width_px, 500),
            "wrap_width":    _safe_int(legend_wrap_w, 28),
            "pad_top":       _safe_float(pad_top,       0.5),
            "pad_sep_above": _safe_float(pad_sep_above, 0.4),
            "pad_sep_below": _safe_float(pad_sep_below, 0.4),
            "gap_slots":     _safe_float(gap_slots,     0.5),
        },
        "chart": {
            "background_color": _parse_color(bg_color_hex, "#ffffff"),
            "resolution_px":    [_safe_int(res_w, 2560), _safe_int(res_h, 1440)],
            "dpi":              _safe_int(dpi, 96),
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
            "left":   _safe_float(sp_left,   0.03),
            "right":  _safe_float(sp_right,  0.92),
            "top":    _safe_float(sp_top,    0.95),
            "bottom": _safe_float(sp_bottom, 0.06),
            "legend_x": _safe_float(sp_lgx,  0.92),
            "legend_y": _safe_float(sp_lgy,  0.83),
        },
        "linewidth_scale_factor": _safe_float(lw_scale, 1.0),
    }


def _populate_form_from_config(cfg: dict):
    series_list = cfg.get("series", [])
    if not isinstance(series_list, list):
        series_list = [series_list]

    rows  = [_series_row(i, s) for i, s in enumerate(series_list)]
    chart = cfg.get("chart", {})
    axis  = cfg.get("axis",  {})

    return rows, len(series_list), {
        "description":  cfg.get("_description", ""),
        "usage":        cfg.get("_usage", ""),
        "chart_title":  chart.get("title", ""),
        "x_label":      axis.get("x_label", ""),
        "y_label":      axis.get("y_label", ""),
        "y_min":        axis.get("y_min", ""),
        "y_max":        axis.get("y_max", ""),
        "x_min":        axis.get("x_min", ""),
        "x_max":        axis.get("x_max", ""),
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
        Output("cfg-x-label",                  "value"),
        Output("cfg-y-label",                  "value"),
        Output("cfg-y-min",                    "value"),
        Output("cfg-y-max",                    "value"),
        Output("cfg-x-min",                    "value"),
        Output("cfg-x-max",                    "value"),
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
            "",       # chart_title
            "", "",   # x_label, y_label
            "", "", "", "",  # y_min, y_max, x_min, x_max
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
            fv["x_label"], fv["y_label"],
            fv["y_min"], fv["y_max"], fv["x_min"], fv["x_max"],
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

    # ── Save chart config (slim) ──────────────────────────────────────────
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
        # Chart (title only — aesthetics live in aesthetics.json)
        State("cfg-chart-title", "value"),
        # Axis
        State("cfg-x-label", "value"),
        State("cfg-y-label", "value"),
        State("cfg-y-min",   "value"),
        State("cfg-y-max",   "value"),
        State("cfg-x-min",   "value"),
        State("cfg-x-max",   "value"),
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
        chart_title,
        x_label, y_label, y_min, y_max, x_min, x_max,
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
        fname = re.sub(r'[<>:"/\\|?*]', "_", fname)

        # Prevent accidentally saving over reserved files
        if fname in _RESERVED:
            return ERR(f"❌ '{fname}' is a reserved filename. Use the dedicated editor for it.")

        out_path = os.path.join(folder.strip(), fname)

        if cfg_type == CFG_TYPE_GANTT:
            cfg = _build_gantt_from_form(
                fname, description, usage,
                gantt_bar_alpha, gantt_bar_height, gantt_edge_hex, gantt_edge_width,
                gantt_test_ids, gantt_color_hexes, gantt_palette_hexes,
            )
            n_ids   = len([k for k in cfg.get("gantt_colors", {})
                           if not k.startswith("_") and k != "default_palette"])
            summary = f"✓ Saved gantt config: {fname}  ({n_ids} Test IDs)"
        else:
            cfg = _build_config_from_form(
                fname, description, usage,
                series_names, series_vcols, series_kws, series_alphas,
                series_color_hexes, series_linewidths, series_linestyles, series_markers,
                chart_title,
                x_label, y_label, y_min, y_max, x_min, x_max,
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

    # ── Save aesthetics ───────────────────────────────────────────────────
    @app.callback(
        Output("aes-save-status", "children"),
        Input("btn-aes-save",     "n_clicks"),
        State("cfgmgr-folder-path",   "value"),
        State("aes-font-family",      "value"),
        State("aes-title-fs",         "value"),
        State("aes-axis-fs",          "value"),
        State("aes-tick-fs",          "value"),
        State("aes-legend-fs",        "value"),
        State("aes-font-scale",       "value"),
        State("aes-bg-color-hex",     "value"),
        State("aes-res-w",            "value"),
        State("aes-res-h",            "value"),
        State("aes-dpi",              "value"),
        State("aes-grid-visible",     "value"),
        State("aes-grid-axis",        "value"),
        State("aes-grid-linestyle",   "value"),
        State("aes-grid-alpha",       "value"),
        State("aes-grid-width",       "value"),
        State("aes-grid-color-hex",   "value"),
        State("aes-sp-left",          "value"),
        State("aes-sp-right",         "value"),
        State("aes-sp-top",           "value"),
        State("aes-sp-bottom",        "value"),
        State("aes-sp-lgx",           "value"),
        State("aes-sp-lgy",           "value"),
        State("aes-legend-width-px",  "value"),
        State("aes-legend-wrap-w",    "value"),
        State("aes-pad-top",          "value"),
        State("aes-pad-sep-above",    "value"),
        State("aes-pad-sep-below",    "value"),
        State("aes-gap-slots",        "value"),
        State("aes-lw-scale",         "value"),
        prevent_initial_call=True,
    )
    def save_aesthetics(
        _, folder,
        font_family, title_fs, axis_fs, tick_fs, legend_fs, font_scale,
        bg_color_hex, res_w, res_h, dpi,
        grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
        sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy,
        legend_width_px, legend_wrap_w,
        pad_top, pad_sep_above, pad_sep_below, gap_slots,
        lw_scale,
    ):
        if not folder or not os.path.isdir(folder.strip()):
            return dbc.Alert("❌ No valid folder loaded.", color="danger", className="py-1 mb-0")

        cfg = _build_aesthetics_from_form(
            font_family, title_fs, axis_fs, tick_fs, legend_fs, font_scale,
            bg_color_hex, res_w, res_h, dpi,
            grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
            sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy,
            legend_width_px, legend_wrap_w,
            pad_top, pad_sep_above, pad_sep_below, gap_slots,
            lw_scale,
        )
        out_path = os.path.join(folder.strip(), _AESTHETICS_FILENAME)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            return dbc.Alert(f"✓ Saved aesthetics.json → {out_path}",
                             color="success", className="py-1 mb-0")
        except Exception as e:
            return dbc.Alert(f"❌ Error saving aesthetics: {e}",
                             color="danger", className="py-1 mb-0")

    # ── Load aesthetics into editor when folder changes ───────────────────
    @app.callback(
        Output("aes-font-family",    "value"),
        Output("aes-title-fs",       "value"),
        Output("aes-axis-fs",        "value"),
        Output("aes-tick-fs",        "value"),
        Output("aes-legend-fs",      "value"),
        Output("aes-font-scale",     "value"),
        Output("aes-bg-color-swatch","value"),
        Output("aes-bg-color-hex",   "value"),
        Output("aes-res-w",          "value"),
        Output("aes-res-h",          "value"),
        Output("aes-dpi",            "value"),
        Output("aes-grid-visible",   "value"),
        Output("aes-grid-axis",      "value"),
        Output("aes-grid-linestyle", "value"),
        Output("aes-grid-alpha",     "value"),
        Output("aes-grid-width",     "value"),
        Output("aes-grid-color-swatch","value"),
        Output("aes-grid-color-hex", "value"),
        Output("aes-sp-left",        "value"),
        Output("aes-sp-right",       "value"),
        Output("aes-sp-top",         "value"),
        Output("aes-sp-bottom",      "value"),
        Output("aes-sp-lgx",         "value"),
        Output("aes-sp-lgy",         "value"),
        Output("aes-legend-width-px","value"),
        Output("aes-legend-wrap-w",  "value"),
        Output("aes-pad-top",        "value"),
        Output("aes-pad-sep-above",  "value"),
        Output("aes-pad-sep-below",  "value"),
        Output("aes-gap-slots",      "value"),
        Output("aes-lw-scale",       "value"),
        Output("aes-load-status",    "children"),
        Input("btn-cfgmgr-refresh",  "n_clicks"),
        Input("cfgmgr-folder-path",  "value"),
        prevent_initial_call=True,
    )
    def load_aesthetics(_, folder):
        DEFAULTS = (
            "sans-serif", 20, 15, 12, 13, 1.0,
            "#ffffff", "#ffffff", 2560, 1440, 96,
            "true", "both", "-", 0.3, 1.0, "#505050", "#505050",
            0.03, 0.92, 0.95, 0.06, 0.92, 0.83,
            500, 28, 0.5, 0.4, 0.4, 0.5, 1.0,
            html.Small("Using built-in defaults (aesthetics.json not found).",
                       className="text-muted"),
        )
        if not folder or not os.path.isdir(folder.strip()):
            return DEFAULTS

        aes_path = os.path.join(folder.strip(), _AESTHETICS_FILENAME)
        if not os.path.exists(aes_path):
            return DEFAULTS

        try:
            with open(aes_path, encoding="utf-8") as f:
                a = json.load(f)
        except Exception as e:
            return (*DEFAULTS[:-1],
                    dbc.Alert(f"❌ Error loading aesthetics.json: {e}",
                              color="danger", className="py-1 mb-0"))

        font  = a.get("font", {})
        chart = a.get("chart", {})
        grid  = a.get("grid", {})
        sp    = a.get("subplot_params", {})
        leg   = a.get("legend", {})
        res   = chart.get("resolution_px", [2560, 1440])
        bg    = chart.get("background_color", "#ffffff")
        gc    = grid.get("color", "#505050")

        return (
            font.get("family", "sans-serif"),
            font.get("title_size", 20),
            font.get("axis_label_size", 15),
            font.get("tick_size", 12),
            font.get("legend_size", 13),
            font.get("scale_factor", 1.0),
            bg, bg,
            res[0] if res else 2560, res[1] if len(res) > 1 else 1440,
            chart.get("dpi", 96),
            "true" if grid.get("visible", True) else "false",
            grid.get("axis", "both"),
            grid.get("linestyle", "-"),
            grid.get("alpha", 0.3),
            grid.get("gridwidth", 1.0),
            gc, gc,
            sp.get("left", 0.03), sp.get("right", 0.92),
            sp.get("top", 0.95),  sp.get("bottom", 0.06),
            sp.get("legend_x", 0.92), sp.get("legend_y", 0.83),
            leg.get("width_px", 500), leg.get("wrap_width", 28),
            leg.get("pad_top", 0.5), leg.get("pad_sep_above", 0.4),
            leg.get("pad_sep_below", 0.4), leg.get("gap_slots", 0.5),
            a.get("linewidth_scale_factor", 1.0),
            dbc.Alert("✓ Loaded aesthetics.json", color="success", className="py-1 mb-0"),
        )

    # Swatch ↔ hex sync for aesthetics bg and grid colour
    for swatch_id, hex_id in [
        ("aes-bg-color-swatch",   "aes-bg-color-hex"),
        ("aes-grid-color-swatch", "aes-grid-color-hex"),
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