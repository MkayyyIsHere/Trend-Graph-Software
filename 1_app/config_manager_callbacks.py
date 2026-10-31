"""1_app/config_manager_callbacks.py — All callbacks for the ⚙️ Config Manager tab.

One list on the left — 🎨 Global style (aesthetics.json), 🏷 Event colours
(gantt.json) and every chart in run order — and the editor for the selected
entry on the right. Each setting has one home:
  • chart on/off per run      → Quick Run table
  • chart order               → ▲▼ here (saved straight to batch_profile.json)
  • Y limits                  → defaults here; Quick Run overrides per run
  • image size, fonts, grid   → Global style
"""

import json
import os
import re
import shutil

from dash import Input, Output, State, ctx, html, no_update, ALL, MATCH
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from utils.constants import (DEFAULT_AESTHETICS_PATH, DEFAULT_CONFIGS_DIR, GANTT_FILENAME,
                             RESERVED_CONFIG_FILENAMES, load_settings, save_settings,
                             user_gantt_path)
from backend.batch_profile import BatchProfileManager
from backend.units import AUTO, base_unit, factor, resolve_unit

from app.config_manager_layout import (
    COLOUR_PALETTES, CFG_TYPE_SERIES, CFG_TYPE_GANTT,
    _series_row, _gantt_color_row, _palette_color_row,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

# Filenames that are never shown in the chart file list
_AESTHETICS_FILENAME   = 'aesthetics.json'
_BATCH_PROFILE_FILENAME = 'batch_profile.json'
_RESERVED = set(RESERVED_CONFIG_FILENAMES)

def _load_last_folder() -> str:
    folder = load_settings().get('last_config_folder', '')
    return folder if folder and os.path.isdir(folder) else ''

def _save_last_folder(folder: str) -> None:
    save_settings(last_config_folder=folder)


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
        vcol = ((series_vcols[i] if series_vcols else "") or "").strip()
        series.append({
            "name":                  (series_names[i]    if series_names    else ""),
            # Metric-based charts pick columns themselves — omit empty fields.
            **({"value_column": vcol} if vcol else {}),
            **({"value_column_keywords": keywords} if keywords else {}),
            "line_color":           _parse_color(series_color_hexes[i] if series_color_hexes else "#1f77b4"),
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

    if y_min is not None:  cfg["axis"]["y_min"] = _safe_float(y_min)
    if y_max is not None:  cfg["axis"]["y_max"] = _safe_float(y_max)
    if x_min not in (None, ""):  cfg["axis"]["x_min"] = str(x_min)
    if x_max not in (None, ""):  cfg["axis"]["x_max"] = str(x_max)

    return cfg


_FORM_AXIS_KEYS = {"x_label", "y_label", "y_min", "y_max", "x_min", "x_max"}


def _merge_into(base: dict, form: dict) -> dict:
    """Overlay the form's fields onto the file being edited, keeping keys the
    form doesn't show (e.g. 'metric', '_metric_help') so a save never breaks
    a metric-based chart."""
    out = dict(base or {})
    for k in ("_description", "_usage", "series"):
        out[k] = form[k]
    out["chart"] = {**(base or {}).get("chart", {}), **form["chart"]}
    out["axis"] = {**{k: v for k, v in (base or {}).get("axis", {}).items()
                      if k not in _FORM_AXIS_KEYS}, **form["axis"]}
    return out


def _build_aesthetics_from_form(
    font_family, title_fs, axis_fs, tick_fs, legend_fs, font_scale,
    bg_color_hex,
    res_w, res_h, dpi,
    grid_visible, grid_axis, grid_ls, grid_alpha, grid_width, grid_color_hex,
    sp_left, sp_right, sp_top, sp_bottom, sp_lgx, sp_lgy,
    legend_wrap_w,
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
        "y_min":        axis.get("y_min"),   # None when absent — never "" so 0.0 displays correctly
        "y_max":        axis.get("y_max"),   # None when absent — never "" so 0.0 displays correctly
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




# ── List rows ─────────────────────────────────────────────────────────────────

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _chip(text, color="light", title=None):
    return dbc.Badge(text, color=color, text_color="dark" if color == "light" else None,
                     className="cm-chip me-1 border", title=title)


def _y_chip(cfg):
    axis = cfg.get("axis", {})
    lo, hi = axis.get("y_min"), axis.get("y_max")
    if lo is None or hi is None:
        return _chip("Y auto", title="Default Y range: fit to the data")
    base = base_unit(cfg)
    unit = resolve_unit(AUTO, base, lo, hi) if base else ""
    k    = factor(unit, base) if base else 1.0
    return _chip(f"Y {lo / k:.4g} – {hi / k:.4g} {unit or ''}".rstrip(),
                 title="Default Y range — Quick Run can override it per run")


def _chart_summary(cfg):
    n = len(cfg.get("series") or [])
    chips = [_chip(cfg["metric"].replace("_", " "), "info", "Columns picked automatically "
                   "for the export brand and wiring") if cfg.get("metric") else None,
             _chip(f"{n} series"), _y_chip(cfg)]
    return [c for c in chips if c], (cfg.get("chart") or {}).get("title")


def _style_summary(path):
    a     = _read_json(path)
    chart = a.get("chart", {})
    res   = chart.get("resolution_px") or [2560, 1440]
    font  = a.get("font", {})
    return [_chip(f"{res[0]}×{res[1]} px"), _chip(f"{chart.get('dpi', 96)} dpi"),
            _chip(font.get("family", "sans-serif")),
            _chip("grid on" if a.get("grid", {}).get("visible", True) else "grid off")]


def _events_source(folder):
    """Where the event colours in use come from (shown under the list row)."""
    if folder and os.path.isfile(os.path.join(folder, GANTT_FILENAME)):
        return "gantt.json in this folder"
    return "this PC" if os.path.isfile(user_gantt_path()) else "built-in"


def _events_summary(gantt_cfg):
    colors  = gantt_cfg.get("gantt_colors", {})
    mapped  = [k for k in colors if not k.startswith("_") and k != "default_palette"]
    palette = colors.get("default_palette") or []
    return [_chip(f"{len(mapped)} test IDs coloured"), _chip(f"palette of {len(palette)}"),
            _chip(f"bar alpha {gantt_cfg.get('gantt', {}).get('bar_alpha', 0.3)}")]


def _row(key, icon, name, chips, subtitle=None, active=False, order=None, n=0, editable=True):
    left = [html.Div([html.Span(icon + " ", className="me-1"), html.B(name, className="small"),
                      html.Small(f"  {subtitle}", className="text-muted") if subtitle else None]),
            html.Div(chips, className="mt-1")]
    right = []
    if order is not None:
        right = [html.Div([
            dbc.Button("▲", id={"type": "cm-up", "file": key}, size="sm", color="light",
                       className="py-0 px-1 me-1 border", disabled=order == 0 or not editable,
                       title="Draw earlier"),
            dbc.Button("▼", id={"type": "cm-down", "file": key}, size="sm", color="light",
                       className="py-0 px-1 border", disabled=order == n - 1 or not editable,
                       title="Draw later"),
        ], className="d-flex")]
    badge = ([dbc.Badge(str(order + 1), color="secondary", className="me-2",
                        style={"minWidth": "24px"})] if order is not None else [])
    attrs = ({"id": {"type": "cm-row", "key": key}, "n_clicks": 0} if editable
             else {"style": {"cursor": "default"}})
    return html.Div(
        [*badge, html.Div(left, className="flex-grow-1"), *right],
        className="cm-row d-flex align-items-center px-3 py-2 border-bottom"
                  + (" active" if active else "") + ("" if editable else " opacity-75"),
        **attrs,
    )


def _ordered_charts(folder):
    bpm = BatchProfileManager()
    bpm.load(folder)
    return [e["filename"] for e in bpm.merge_with_folder(folder)]


# ── Registration ──────────────────────────────────────────────────────────────

def register_config_manager_callbacks(app, state):
    """Register all Config Manager callbacks on *app*."""

    def _folder(value):
        value = (value or "").strip().strip('"')
        return value if value and os.path.isdir(value) else ""

    def _picker(title, output):
        app.clientside_callback(
            f"""
            function(n) {{
                if (!n) return window.dash_clientside.no_update;
                return fetch('/api/pick-folder?title={title.replace(" ", "%20")}')
                    .then(r => r.json())
                    .then(d => d.path || window.dash_clientside.no_update)
                    .catch(() => window.dash_clientside.no_update);
            }}
            """,
            output[0], output[1], prevent_initial_call=True,
        )

    # ── Folder: browse / restore / built-in / copy built-in ──────────────────
    _picker("Select Config Folder", (Output("cfgmgr-folder-path", "value", allow_duplicate=True),
                                     Input("btn-cfgmgr-browse", "n_clicks")))
    _picker("Copy built-in charts to folder", (Output("store-cm-copy-target", "data"),
                                               Input("btn-cfgmgr-copy", "n_clicks")))

    @app.callback(
        Output("cfgmgr-folder-path", "value"),
        Input("cfgmgr-folder-path",  "id"),
    )
    def restore_last_folder(_):
        return _load_last_folder()

    @app.callback(
        Output("cfgmgr-folder-path", "value", allow_duplicate=True),
        Input("btn-cfgmgr-builtin", "n_clicks"),
        prevent_initial_call=True,
    )
    def use_builtin(_):
        return ""

    @app.callback(
        Output("cfgmgr-folder-path", "value", allow_duplicate=True),
        Output("cfgmgr-status", "children", allow_duplicate=True),
        Input("store-cm-copy-target", "data"),
        prevent_initial_call=True,
    )
    def copy_builtin(target):
        if not target or not os.path.isdir(target):
            raise PreventUpdate
        copied, kept = 0, 0
        for f in os.listdir(DEFAULT_CONFIGS_DIR):
            if not f.lower().endswith(".json"):
                continue
            dst = os.path.join(target, f)
            if os.path.exists(dst):
                kept += 1
                continue
            try:
                shutil.copy2(os.path.join(DEFAULT_CONFIGS_DIR, f), dst)
                copied += 1
            except OSError as e:
                return no_update, dbc.Alert(f"❌ Copy failed: {e}", color="danger",
                                            className="py-1 mb-0")
        note = f" ({kept} existing file(s) kept)" if kept else ""
        return target, dbc.Alert(f"✓ Copied {copied} file(s) to {target}{note}",
                                 color="success", className="py-1 mb-0")

    # ── List ─────────────────────────────────────────────────────────────────
    @app.callback(
        Output("cfgmgr-list",          "children"),
        Output("cfgmgr-folder-status", "children"),
        Output("btn-cfgmgr-new",       "disabled"),
        Input("cfgmgr-folder-path",    "value"),
        Input("btn-cfgmgr-refresh",    "n_clicks"),
        Input("store-cm-version",      "data"),
        Input("store-cm-selected",     "data"),
    )
    def render_list(folder_value, _r, _v, selected):
        folder = _folder(folder_value)
        typed  = (folder_value or "").strip()
        if typed and not folder:
            status = html.Span(f"✗ Folder not found: {typed}", className="text-danger")
        elif folder:
            _save_last_folder(folder)
            status = f"Editing {folder} — Quick Run uses these charts."
        else:
            _save_last_folder("")
            status = ("Quick Run uses the built-in charts (read-only). Copy them to a folder "
                      "to change charts or Global style.")
        sel_key = f"{selected['kind']}:{selected.get('file') or ''}" if selected else None
        src     = folder or DEFAULT_CONFIGS_DIR
        aes     = os.path.join(src, _AESTHETICS_FILENAME)
        rows = [
            _row("style:", "🎨", "Global style",
                 _style_summary(aes if os.path.isfile(aes) else DEFAULT_AESTHETICS_PATH),
                 subtitle="aesthetics.json", active=sel_key == "style:"),
            _row("events:", "🏷", "Event colours",
                 _events_summary(state.refresh_gantt(folder).config or {}),
                 subtitle=_events_source(folder), active=sel_key == "events:"),
            html.Div(html.Small("Charts — drawn in this order", className="text-muted fw-semibold"),
                     className="px-3 pt-2 pb-1 bg-light border-bottom"),
        ]
        files = _ordered_charts(src)
        for i, f in enumerate(files):
            cfg = _read_json(os.path.join(src, f))
            if _detect_config_type(cfg) == CFG_TYPE_GANTT:
                chips, title = _events_summary(cfg), "event colours"
            else:
                chips, title = _chart_summary(cfg)
            rows.append(_row(f"chart:{f}", "📈", os.path.splitext(f)[0], chips, subtitle=title,
                             active=sel_key == f"chart:{f}", order=i, n=len(files),
                             editable=bool(folder)))
        if not files:
            rows.append(html.P("No chart configs in this folder — click ➕ New chart.",
                               className="text-muted small m-3"))
        return rows, status, not folder

    # ── Selection ────────────────────────────────────────────────────────────
    @app.callback(
        Output("store-cm-selected", "data", allow_duplicate=True),
        Input({"type": "cm-row", "key": ALL}, "n_clicks"),
        Input("btn-cfgmgr-new", "n_clicks"),
        State("store-cm-selected", "data"),
        prevent_initial_call=True,
    )
    def select(_clicks, _new, current):
        trig = ctx.triggered_id
        if trig == "btn-cfgmgr-new":
            return {"kind": "new", "file": None}
        if not isinstance(trig, dict) or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        kind, _, f = trig["key"].partition(":")
        new = {"kind": kind, "file": f or None}
        if new == current:
            raise PreventUpdate
        return new

    # A folder change drops a chart selection that may no longer exist.
    @app.callback(
        Output("store-cm-selected", "data", allow_duplicate=True),
        Input("cfgmgr-folder-path", "value"),
        State("store-cm-selected", "data"),
        prevent_initial_call=True,
    )
    def reset_selection(_, current):
        if current and current["kind"] in ("chart", "new"):
            return None
        raise PreventUpdate

    # ── Order (▲▼) — saved straight to batch_profile.json ───────────────────
    @app.callback(
        Output("store-cm-version", "data", allow_duplicate=True),
        Output("cfgmgr-status", "children", allow_duplicate=True),
        Input({"type": "cm-up", "file": ALL}, "n_clicks"),
        Input({"type": "cm-down", "file": ALL}, "n_clicks"),
        State("cfgmgr-folder-path", "value"),
        State("store-cm-version", "data"),
        prevent_initial_call=True,
    )
    def move(_up, _down, folder_value, version):
        trig, folder = ctx.triggered_id, _folder(folder_value)
        if not isinstance(trig, dict) or not ctx.triggered[0]["value"] or not folder:
            raise PreventUpdate
        files = _ordered_charts(folder)
        name  = trig["file"].partition(":")[2]
        if name not in files:
            raise PreventUpdate
        i = files.index(name)
        j = i + (-1 if trig["type"] == "cm-up" else 1)
        if not 0 <= j < len(files):
            raise PreventUpdate
        files[i], files[j] = files[j], files[i]
        if not BatchProfileManager().save(folder, files):
            return no_update, dbc.Alert("❌ Could not save the order — check folder permissions.",
                                        color="danger", className="py-1 mb-0")
        return (version or 0) + 1, no_update

    # ── Editor panel: which form + header buttons ────────────────────────────
    hidden, shown, btn = {"display": "none"}, {"display": "block"}, {"display": "inline-block"}

    @app.callback(
        Output("cm-placeholder",     "style"),
        Output("cm-chart-editor",    "style"),
        Output("cm-style-editor",    "style"),
        Output("cfg-editor-title",   "children"),
        Output("btn-cfg-save",       "style"),
        Output("btn-aes-save",       "style"),
        Output("btn-cm-revert",      "style"),
        Output("btn-cfgmgr-clone",   "style"),
        Output("btn-cfgmgr-delete",  "style"),
        Output("cfg-filename-row",   "style"),
        Input("store-cm-selected",   "data"),
        Input("store-cfgmgr-edit-mode", "data"),
        State("cfgmgr-folder-path",  "value"),
    )
    def editor_panel(selected, mode, folder_value):
        if not selected:
            return (shown, hidden, hidden, "Select an entry on the left",
                    hidden, hidden, hidden, hidden, hidden, hidden)
        kind, f = selected["kind"], selected.get("file")
        name = os.path.splitext(f or "")[0]
        if kind == "style":
            can_edit = bool(_folder(folder_value))
            return (hidden, hidden, shown,
                    "🎨 Global style" + ("" if can_edit else " — built-in (read-only)"),
                    hidden, btn if can_edit else hidden, btn, hidden, hidden, hidden)
        if kind == "events":
            return (hidden, shown, hidden, "🏷 Event colours",
                    btn, hidden, btn, hidden, hidden, hidden)
        if kind == "new":
            return (hidden, shown, hidden, "➕ New chart",
                    btn, hidden, hidden, hidden, hidden, shown)
        if mode == "clone":
            return (hidden, shown, hidden, f"📋 Copy of {name}",
                    btn, hidden, btn, hidden, hidden, shown)
        return (hidden, shown, hidden, f"📈 {name}", btn, hidden, btn, btn, btn, hidden)

    # ── Chart / event-colour form: load from disk ────────────────────────────
    series_defaults = ([_series_row(0)], 1, "", "", "", None, None, "", "")
    gantt_defaults  = (0.3, 1.0, "#000000", "#000000", 0.2, [], 0, [], 0)

    @app.callback(
        Output("store-cfgmgr-edit-mode",       "data"),
        Output("cfg-filename",                 "value"),
        Output("cfg-description",              "value"),
        Output("cfg-usage",                    "value"),
        Output("cfg-series-container",         "children"),
        Output("store-series-count",           "data"),
        Output("cfg-chart-title",              "value"),
        Output("cfg-x-label",                  "value"),
        Output("cfg-y-label",                  "value"),
        Output("cfg-y-min",                    "value"),
        Output("cfg-y-max",                    "value"),
        Output("cfg-x-min",                    "value"),
        Output("cfg-x-max",                    "value"),
        Output("cfg-gantt-bar-alpha",          "value"),
        Output("cfg-gantt-bar-height",         "value"),
        Output("cfg-gantt-edge-swatch",        "value"),
        Output("cfg-gantt-edge-hex",           "value"),
        Output("cfg-gantt-edge-width",         "value"),
        Output("cfg-gantt-colors-container",   "children"),
        Output("store-gantt-color-count",      "data"),
        Output("cfg-gantt-palette-container",  "children"),
        Output("store-gantt-palette-count",    "data"),
        Output("cfg-gantt-collapse",           "is_open"),
        Output("cfg-series-sections-collapse", "is_open"),
        Output("store-cfg-type",               "data"),
        Output("cfg-type-badge",               "children"),
        Input("store-cm-selected",             "data"),
        Input("store-cm-reload",               "data"),
        Input("btn-cfgmgr-clone",              "n_clicks"),
        State("cfgmgr-folder-path",            "value"),
        prevent_initial_call=True,
    )
    def load_form(selected, _reload, _clone, folder_value):
        if not selected or selected["kind"] == "style":
            raise PreventUpdate
        kind = selected["kind"]
        if ctx.triggered_id == "btn-cfgmgr-clone":
            if kind != "chart":
                raise PreventUpdate
            # Keep the loaded form; only the target file name changes.
            stem = os.path.splitext(selected["file"])[0]
            return ("clone", f"{stem}_copy.json", *([no_update] * 24))
        if kind == "new":
            return ("new", "", "", "", *series_defaults, *gantt_defaults,
                    False, True, CFG_TYPE_SERIES, None)

        path = (state.refresh_gantt(_folder(folder_value)).config_path if kind == "events"
                else os.path.join(_folder(folder_value), selected["file"]))
        cfg = _read_json(path) if path else {}
        if kind == "events" or _detect_config_type(cfg) == CFG_TYPE_GANTT:
            gv = _populate_gantt_form(cfg)
            badge = (html.Small("Colours of the test-schedule bars on every chart. "
                                + ("Saved as gantt.json in the config folder, so everyone "
                                   "using the folder gets them." if _folder(folder_value) else
                                   "Saved for this PC (replaces the built-in colours)."),
                                className="text-muted")
                     if kind == "events" else None)
            return ("events" if kind == "events" else "edit", selected.get("file") or "",
                    cfg.get("_description", ""), cfg.get("_usage", ""),
                    *series_defaults,
                    gv["bar_alpha"], gv["bar_height"], gv["edge_hex"], gv["edge_hex"],
                    gv["edge_width"], gv["color_rows"], gv["n_colors"],
                    gv["palette_rows"], gv["n_palette"],
                    True, False, CFG_TYPE_GANTT, badge)
        rows, n_series, fv = _populate_form_from_config(cfg)
        badge = (html.Small(f"Metric: {cfg['metric']} — columns are picked automatically for "
                            "the export brand and wiring; the series below are colour/style "
                            "slots in phase order.", className="text-muted")
                 if cfg.get("metric") else None)
        return ("edit", selected["file"], fv["description"], fv["usage"],
                rows, n_series, fv["chart_title"], fv["x_label"], fv["y_label"],
                fv["y_min"], fv["y_max"], fv["x_min"], fv["x_max"],
                *gantt_defaults, False, True, CFG_TYPE_SERIES, badge)

    @app.callback(
        Output("store-cm-reload", "data", allow_duplicate=True),
        Output("cfg-save-status", "children", allow_duplicate=True),
        Input("btn-cm-revert", "n_clicks"),
        State("store-cm-reload", "data"),
        prevent_initial_call=True,
    )
    def revert(_, n):
        return (n or 0) + 1, html.Span("↺ Reloaded from file", className="text-muted")

    # ── Add / remove rows in the chart & gantt forms ─────────────────────────
    for add_btn, container, count_store, row_fn in [
        ("btn-add-series",        "cfg-series-container",        "store-series-count",        _series_row),
        ("btn-add-gantt-color",   "cfg-gantt-colors-container",  "store-gantt-color-count",   _gantt_color_row),
        ("btn-add-palette-color", "cfg-gantt-palette-container", "store-gantt-palette-count", _palette_color_row),
    ]:
        def _add(_, count, current, row_fn=row_fn):
            count = count or 0
            return (current or []) + [row_fn(count)], count + 1
        app.callback(
            Output(container,   "children", allow_duplicate=True),
            Output(count_store, "data",     allow_duplicate=True),
            Input(add_btn, "n_clicks"),
            State(count_store, "data"),
            State(container,   "children"),
            prevent_initial_call=True,
        )(_add)

    for btn_type, container, count_store, prefix in [
        ("btn-remove-series",        "cfg-series-container",        "store-series-count",        "series-card"),
        ("btn-remove-gantt-color",   "cfg-gantt-colors-container",  "store-gantt-color-count",   "gantt-color-card"),
        ("btn-remove-palette-color", "cfg-gantt-palette-container", "store-gantt-palette-count", "gantt-palette-card"),
    ]:
        def _remove(n_clicks_list, current, count, prefix=prefix):
            if not any(n for n in n_clicks_list if n):
                raise PreventUpdate
            idx  = ctx.triggered_id["index"]
            rows = [r for r in (current or [])
                    if not (isinstance(r, dict)
                            and r.get("props", {}).get("id") == f"{prefix}-{idx}")]
            return rows, max(0, (count or 1) - 1)
        app.callback(
            Output(container,   "children", allow_duplicate=True),
            Output(count_store, "data",     allow_duplicate=True),
            Input({"type": btn_type, "index": ALL}, "n_clicks"),
            State(container,    "children"),
            State(count_store,  "data"),
            prevent_initial_call=True,
        )(_remove)

    # ── Colour swatch ↔ hex sync ─────────────────────────────────────────────
    to_hex = "function(v) { return v; }"
    to_swatch = """function(v) {
        if (!v) return window.dash_clientside.no_update;
        v = v.trim();
        return /^#[0-9a-fA-F]{6}$/.test(v) ? v : window.dash_clientside.no_update;
    }"""
    for kind in ("series-color", "gantt-color", "gantt-palette"):
        app.clientside_callback(to_hex,
                                Output({"type": f"{kind}-hex", "index": MATCH}, "value"),
                                Input({"type": f"{kind}-swatch", "index": MATCH}, "value"),
                                prevent_initial_call=True)
        app.clientside_callback(to_swatch,
                                Output({"type": f"{kind}-swatch", "index": MATCH}, "value"),
                                Input({"type": f"{kind}-hex", "index": MATCH}, "value"),
                                prevent_initial_call=True)
    for swatch_id, hex_id in [("cfg-gantt-edge-swatch", "cfg-gantt-edge-hex"),
                              ("aes-bg-color-swatch",   "aes-bg-color-hex"),
                              ("aes-grid-color-swatch", "aes-grid-color-hex")]:
        app.clientside_callback(to_hex, Output(hex_id, "value", allow_duplicate=True),
                                Input(swatch_id, "value"), prevent_initial_call=True)
        app.clientside_callback(to_swatch, Output(swatch_id, "value", allow_duplicate=True),
                                Input(hex_id, "value"), prevent_initial_call=True)

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

    # ── Save chart / event colours ───────────────────────────────────────────
    @app.callback(
        Output("cfg-save-status",   "children", allow_duplicate=True),
        Output("store-cm-version",  "data",     allow_duplicate=True),
        Output("store-cm-selected", "data",     allow_duplicate=True),
        Output("store-cfgmgr-edit-mode", "data", allow_duplicate=True),
        Output("store-cm-dirty",    "data",     allow_duplicate=True),
        Input("btn-cfg-save", "n_clicks"),
        State("store-cm-selected",      "data"),
        State("store-cfgmgr-edit-mode", "data"),
        State("store-cfg-type",         "data"),
        State("cfgmgr-folder-path",     "value"),
        State("cfg-filename",           "value"),
        State("cfg-description",        "value"),
        State("cfg-usage",              "value"),
        State({"type": "series-name",       "index": ALL}, "value"),
        State({"type": "series-value-col",  "index": ALL}, "value"),
        State({"type": "series-keywords",   "index": ALL}, "value"),
        State({"type": "series-alpha",      "index": ALL}, "value"),
        State({"type": "series-color-hex",  "index": ALL}, "value"),
        State({"type": "series-linewidth",  "index": ALL}, "value"),
        State({"type": "series-linestyle",  "index": ALL}, "value"),
        State({"type": "series-marker",     "index": ALL}, "value"),
        State("cfg-chart-title", "value"),
        State("cfg-x-label", "value"),
        State("cfg-y-label", "value"),
        State("cfg-y-min",   "value"),
        State("cfg-y-max",   "value"),
        State("cfg-x-min",   "value"),
        State("cfg-x-max",   "value"),
        State("cfg-gantt-bar-alpha",  "value"),
        State("cfg-gantt-bar-height", "value"),
        State("cfg-gantt-edge-hex",   "value"),
        State("cfg-gantt-edge-width", "value"),
        State({"type": "gantt-test-id",     "index": ALL}, "value"),
        State({"type": "gantt-color-hex",   "index": ALL}, "value"),
        State({"type": "gantt-palette-hex", "index": ALL}, "value"),
        State("store-cm-version", "data"),
        prevent_initial_call=True,
    )
    def save_config(
        _, selected, mode, cfg_type, folder_value, filename, description, usage,
        series_names, series_vcols, series_kws, series_alphas,
        series_color_hexes, series_linewidths, series_linestyles, series_markers,
        chart_title, x_label, y_label, y_min, y_max, x_min, x_max,
        gantt_bar_alpha, gantt_bar_height, gantt_edge_hex, gantt_edge_width,
        gantt_test_ids, gantt_color_hexes, gantt_palette_hexes, version,
    ):
        def err(msg):
            return html.Span(msg, className="text-danger"), no_update, no_update, no_update, no_update

        if not selected:
            raise PreventUpdate
        folder = _folder(folder_value)
        if mode == "events":
            out_path = os.path.join(folder, GANTT_FILENAME) if folder else user_gantt_path()
            fname    = os.path.basename(out_path)
        else:
            if not folder:
                return err("❌ Choose a config folder first.")
            fname = (filename or "").strip()
            if not fname:
                return err("❌ Enter a file name.")
            if not fname.lower().endswith(".json"):
                fname += ".json"
            fname = re.sub(r'[<>:"/\\|?*]', "_", fname)
            if fname in _RESERVED:
                return err(f"❌ '{fname}' is a reserved name.")
            out_path = os.path.join(folder, fname)
            if mode in ("new", "clone") and os.path.exists(out_path):
                return err(f"❌ {fname} already exists — pick another name.")

        if cfg_type == CFG_TYPE_GANTT:
            cfg = _build_gantt_from_form(
                fname, description, usage,
                gantt_bar_alpha, gantt_bar_height, gantt_edge_hex, gantt_edge_width,
                gantt_test_ids, gantt_color_hexes, gantt_palette_hexes)
            # Keep gantt keys the form doesn't show (e.g. 'label_color').
            prev = _read_json(state.refresh_gantt(folder).config_path) or {}
            cfg["gantt"] = {**prev.get("gantt", {}), **cfg.get("gantt", {})}
        else:
            form = _build_config_from_form(
                fname, description, usage,
                series_names, series_vcols, series_kws, series_alphas,
                series_color_hexes, series_linewidths, series_linestyles, series_markers,
                chart_title, x_label, y_label, y_min, y_max, x_min, x_max)
            # Edit / clone keep the source file's other keys (e.g. 'metric').
            src = (os.path.join(folder, selected["file"])
                   if selected.get("file") and mode in ("edit", "clone") else None)
            cfg = _merge_into(_read_json(src) if src else {}, form)

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return err(f"❌ Could not save: {e}")

        if mode == "events":
            state.refresh_gantt(folder)
            return (html.Span("✓ Saved event colours", className="text-success"),
                    (version or 0) + 1, no_update, no_update, False)
        if mode in ("new", "clone"):
            # New charts join the run order at the end.
            files = _ordered_charts(folder)
            BatchProfileManager().save(folder, files + ([fname] if fname not in files else []))
        return (html.Span(f"✓ Saved {fname}", className="text-success"), (version or 0) + 1,
                {"kind": "chart", "file": fname}, "edit", False)

    # ── Unsaved edits ────────────────────────────────────────────────────────
    # Edits live only in the form until Save, so flag them: user typing/clicking
    # inside the editor marks it dirty (form loads are programmatic, so they
    # don't). Leaving the entry or generating while dirty asks first.
    app.clientside_callback(
        """
        function(id) {
            if (window._cmGuard) return window.dash_clientside.no_update;
            window._cmGuard = true;
            var inEditor = function(el) {
                return el && el.closest && el.closest('#cm-chart-editor, #cm-style-editor');
            };
            var mark = function(e) {
                if (!e.isTrusted || !inEditor(e.target) || window._cmDirty) return;
                window._cmDirty = true;
                window.dash_clientside.set_props('store-cm-dirty', {data: true});
            };
            document.addEventListener('input', mark, true);
            document.addEventListener('change', mark, true);
            document.addEventListener('click', function(e) {
                if (!e.isTrusted || !e.target.closest) return;
                var b = e.target.closest('button');
                if (b && inEditor(b)) { mark(e); return; }
                if (!window._cmDirty) return;
                var row = e.target.closest('.cm-row:not(.active), #btn-cfgmgr-new');
                var run = e.target.closest('#wz-run');
                if (!row && !run) return;
                var msg = run
                    ? 'Config Manager has unsaved changes. This run will NOT use them.\\n\\n'
                      + 'Click Cancel, then Save in Config Manager to use them.\\n\\nGenerate anyway?'
                    : 'Discard your unsaved changes?';
                if (!window.confirm(msg)) { e.stopPropagation(); e.preventDefault(); }
            }, true);
            return '';
        }
        """,
        Output("store-cm-guard", "data"),
        Input("store-cm-guard", "id"),
    )

    app.clientside_callback(
        """
        function(dirty) {
            window._cmDirty = !!dirty;
            var c = dirty ? 'warning' : 'primary';
            return [c, c, dirty ? '● Unsaved changes' : ''];
        }
        """,
        Output("btn-cfg-save", "color"),
        Output("btn-aes-save", "color"),
        Output("cm-dirty-note", "children"),
        Input("store-cm-dirty", "data"),
    )

    # Another entry selected or reverted → the form matches the file again.
    @app.callback(
        Output("store-cm-dirty", "data", allow_duplicate=True),
        Input("store-cm-selected", "data"),
        Input("store-cm-reload", "data"),
        prevent_initial_call=True,
    )
    def clear_dirty(*_):
        return False

    # ── Global style (aesthetics.json) ───────────────────────────────────────
    aes_ids = ["aes-font-family", "aes-title-fs", "aes-axis-fs", "aes-tick-fs", "aes-legend-fs",
               "aes-font-scale", "aes-bg-color-hex", "aes-res-w", "aes-res-h", "aes-dpi",
               "aes-grid-visible", "aes-grid-axis", "aes-grid-linestyle", "aes-grid-alpha",
               "aes-grid-width", "aes-grid-color-hex", "aes-sp-left", "aes-sp-right",
               "aes-sp-top", "aes-sp-bottom", "aes-sp-lgx", "aes-sp-lgy", "aes-legend-wrap-w",
               "aes-pad-top", "aes-pad-sep-above", "aes-pad-sep-below", "aes-gap-slots",
               "aes-lw-scale"]   # order = _build_aesthetics_from_form's arguments

    @app.callback(
        Output("cfg-save-status",   "children", allow_duplicate=True),
        Output("store-cm-version",  "data",     allow_duplicate=True),
        Output("store-cm-dirty",    "data",     allow_duplicate=True),
        Input("btn-aes-save", "n_clicks"),
        State("cfgmgr-folder-path", "value"),
        State("store-cm-version", "data"),
        *[State(i, "value") for i in aes_ids],
        prevent_initial_call=True,
    )
    def save_aesthetics(_, folder_value, version, *form):
        folder = _folder(folder_value)
        if not folder:
            return (html.Span("❌ Choose a config folder first.", className="text-danger"),
                    no_update, no_update)
        out_path = os.path.join(folder, _AESTHETICS_FILENAME)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(_build_aesthetics_from_form(*form), f, indent=2, ensure_ascii=False)
            state.config.reload_aesthetics(out_path)
        except Exception as e:
            return html.Span(f"❌ Could not save: {e}", className="text-danger"), no_update, no_update
        return html.Span("✓ Saved Global style", className="text-success"), (version or 0) + 1, False

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
        Output("aes-legend-wrap-w",  "value"),
        Output("aes-pad-top",        "value"),
        Output("aes-pad-sep-above",  "value"),
        Output("aes-pad-sep-below",  "value"),
        Output("aes-gap-slots",      "value"),
        Output("aes-lw-scale",       "value"),
        Output("aes-load-status",    "children"),
        Input("store-cm-selected",   "data"),
        Input("store-cm-reload",     "data"),
        State("cfgmgr-folder-path",  "value"),
        prevent_initial_call=True,
    )
    def load_aesthetics(selected, _reload, folder_value):
        if not selected or selected["kind"] != "style":
            raise PreventUpdate
        folder   = _folder(folder_value)
        aes_path = os.path.join(folder, _AESTHETICS_FILENAME) if folder else ""
        if not os.path.isfile(aes_path):
            aes_path = DEFAULT_AESTHETICS_PATH
        if not folder:
            note = html.Small("Built-in style (read-only) — copy the built-in charts to a "
                              "folder to change it.", className="text-muted")
        elif aes_path == DEFAULT_AESTHETICS_PATH:
            note = html.Small("Showing the built-in style — saving creates aesthetics.json "
                              "in this folder.", className="text-muted")
        else:
            note = ""
        a     = _read_json(aes_path)
        font  = a.get("font", {})
        chart = a.get("chart", {})
        grid  = a.get("grid", {})
        sp    = a.get("subplot_params", {})
        leg   = a.get("legend", {})
        res   = chart.get("resolution_px") or [2560, 1440]
        bg    = chart.get("background_color", "#ffffff")
        gc    = grid.get("color", "#505050")
        return (
            font.get("family", "sans-serif"), font.get("title_size", 20),
            font.get("axis_label_size", 15), font.get("tick_size", 12),
            font.get("legend_size", 13), font.get("scale_factor", 1.0),
            bg, bg, res[0], res[1] if len(res) > 1 else 1440, chart.get("dpi", 96),
            "true" if grid.get("visible", True) else "false",
            grid.get("axis", "both"), grid.get("linestyle", "-"),
            grid.get("alpha", 0.3), grid.get("gridwidth", 1.0), gc, gc,
            sp.get("left", 0.03), sp.get("right", 0.92), sp.get("top", 0.95),
            sp.get("bottom", 0.06), sp.get("legend_x", 0.92), sp.get("legend_y", 0.83),
            leg.get("wrap_width", 28), leg.get("pad_top", 0.5), leg.get("pad_sep_above", 0.4),
            leg.get("pad_sep_below", 0.4), leg.get("gap_slots", 0.5),
            a.get("linewidth_scale_factor", 1.0),
            note,
        )

    # ── Delete (with confirmation) ───────────────────────────────────────────
    @app.callback(
        Output("cfg-confirm-delete-modal", "is_open", allow_duplicate=True),
        Output("cfg-delete-confirm-text",  "children"),
        Input("btn-cfgmgr-delete",         "n_clicks"),
        State("store-cm-selected",         "data"),
        prevent_initial_call=True,
    )
    def open_delete_confirm(_, selected):
        if not selected or selected["kind"] != "chart":
            raise PreventUpdate
        return True, f"Permanently delete \"{selected['file']}\"?"

    @app.callback(
        Output("cfg-confirm-delete-modal", "is_open", allow_duplicate=True),
        Input("btn-cfg-cancel-delete",     "n_clicks"),
        prevent_initial_call=True,
    )
    def cancel_delete(_):
        return False

    @app.callback(
        Output("cfg-confirm-delete-modal", "is_open",  allow_duplicate=True),
        Output("cfgmgr-status",            "children", allow_duplicate=True),
        Output("store-cm-selected",        "data",     allow_duplicate=True),
        Output("store-cm-version",         "data",     allow_duplicate=True),
        Input("btn-cfg-confirm-delete",    "n_clicks"),
        State("store-cm-selected",         "data"),
        State("cfgmgr-folder-path",        "value"),
        State("store-cm-version",          "data"),
        prevent_initial_call=True,
    )
    def confirm_delete(_, selected, folder_value, version):
        folder = _folder(folder_value)
        if not selected or selected["kind"] != "chart" or not folder:
            raise PreventUpdate
        try:
            os.remove(os.path.join(folder, selected["file"]))
        except Exception as e:
            return False, dbc.Alert(f"❌ Delete failed: {e}", color="danger",
                                    className="py-1 mb-0"), no_update, no_update
        files = [f for f in _ordered_charts(folder) if f != selected["file"]]
        BatchProfileManager().save(folder, files)
        return (False, dbc.Alert(f"🗑️ Deleted {selected['file']}", color="warning",
                                 className="py-1 mb-0"), None, (version or 0) + 1)
