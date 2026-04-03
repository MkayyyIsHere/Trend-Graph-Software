"""1_app/config_manager_layout.py — Layout for the ⚙️ Config Manager tab."""

from dash import dcc, html
import dash_bootstrap_components as dbc

# ── Colour palettes available for bulk-apply ────────────────────────────────
COLOUR_PALETTES = {
    "Matplotlib Tab10": [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ],
    "Plotly Default": [
        "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
        "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
    ],
    "Seaborn Deep": [
        "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
        "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
    ],
    "Vibrant Contrast": [
        "#E63946", "#457B9D", "#2A9D8F", "#E9C46A", "#F4A261",
        "#264653", "#A8DADC", "#F1FAEE", "#6D6875", "#B5838D",
    ],
}

LINESTYLES  = ["-", "--", "-.", ":", "None"]
MARKERS     = ["none", "o", "s", "^", "v", "D", "x", "+", "*"]

# ── Config type constants ────────────────────────────────────────────────────
CFG_TYPE_SERIES     = "series"
CFG_TYPE_GANTT      = "gantt"
CFG_TYPE_AESTHETICS = "aesthetics"


def _gantt_color_row(idx: int, test_id: str = "", color: str = "#1f77b4") -> dbc.Card:
    """Build one Test ID → colour mapping row for the gantt editor."""
    i = idx
    return dbc.Card(
        className="mb-1 border-secondary",
        id=f"gantt-color-card-{i}",
        children=[
            dbc.CardBody(
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Test ID", className="small fw-semibold"),
                        dbc.Input(
                            id={"type": "gantt-test-id", "index": i},
                            value=test_id,
                            placeholder="e.g. HLT7",
                            size="sm",
                            style={"fontFamily": "monospace"},
                        ),
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Colour", className="small fw-semibold"),
                        html.Div([
                            dbc.Input(
                                id={"type": "gantt-color-swatch", "index": i},
                                type="color", value=color,
                                style={"width": "38px", "height": "31px", "padding": "2px",
                                       "border": "1px solid #ced4da",
                                       "borderRadius": "4px 0 0 4px", "cursor": "pointer"},
                            ),
                            dbc.Input(
                                id={"type": "gantt-color-hex", "index": i},
                                value=color, placeholder="#rrggbb", size="sm",
                                style={"borderRadius": "0 4px 4px 0",
                                       "fontFamily": "monospace", "width": "95px"},
                            ),
                        ], className="d-flex"),
                    ], width=5),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small fw-semibold d-block"),
                        dbc.Button(
                            "✕",
                            id={"type": "btn-remove-gantt-color", "index": i},
                            color="danger", size="sm", outline=True,
                        ),
                    ], width=3, className="d-flex flex-column align-items-start"),
                ], align="center"),
                className="py-2",
            ),
        ],
    )


def _palette_color_row(idx: int, color: str = "#1f77b4") -> dbc.Card:
    """Build one default-palette colour entry row."""
    i = idx
    return dbc.Card(
        className="mb-1 border-secondary",
        id=f"gantt-palette-card-{i}",
        children=[
            dbc.CardBody(
                dbc.Row([
                    dbc.Col([
                        dbc.Label(f"Colour {i + 1}", className="small fw-semibold"),
                        html.Div([
                            dbc.Input(
                                id={"type": "gantt-palette-swatch", "index": i},
                                type="color", value=color,
                                style={"width": "38px", "height": "31px", "padding": "2px",
                                       "border": "1px solid #ced4da",
                                       "borderRadius": "4px 0 0 4px", "cursor": "pointer"},
                            ),
                            dbc.Input(
                                id={"type": "gantt-palette-hex", "index": i},
                                value=color, placeholder="#rrggbb", size="sm",
                                style={"borderRadius": "0 4px 4px 0",
                                       "fontFamily": "monospace", "width": "95px"},
                            ),
                        ], className="d-flex"),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("\u00a0", className="small fw-semibold d-block"),
                        dbc.Button(
                            "✕",
                            id={"type": "btn-remove-palette-color", "index": i},
                            color="danger", size="sm", outline=True,
                        ),
                    ], width=6, className="d-flex flex-column align-items-start"),
                ], align="center"),
                className="py-2",
            ),
        ],
    )


def _gantt_editor_section():
    """Gantt/Event config editor section (shown when editing a gantt config)."""
    return html.Div(id="cfg-gantt-section", children=[
        # ── Gantt Bar Settings ───────────────────────────────────────────
        dbc.Row([dbc.Col(html.H6("🎨 Gantt Bar Settings", className="fw-bold text-success"))]),
        dbc.Row([
            dbc.Col([
                dbc.Label("Bar Alpha", className="small fw-semibold"),
                dbc.Input(id="cfg-gantt-bar-alpha", value=0.3, type="number",
                          min=0.0, max=1.0, step=0.05, size="sm"),
                html.Small("0.0 = invisible, 1.0 = fully opaque", className="text-muted"),
            ], width=2),
            dbc.Col([
                dbc.Label("Bar Height Ratio", className="small fw-semibold"),
                dbc.Input(id="cfg-gantt-bar-height", value=1.0, type="number",
                          min=0.1, max=1.0, step=0.05, size="sm"),
                html.Small("Fraction of allocated slot height", className="text-muted"),
            ], width=2),
            dbc.Col([
                dbc.Label("Edge Colour", className="small fw-semibold"),
                html.Div([
                    dbc.Input(id="cfg-gantt-edge-swatch", type="color", value="#000000",
                              style={"width": "38px", "height": "31px", "padding": "2px",
                                     "border": "1px solid #ced4da",
                                     "borderRadius": "4px 0 0 4px", "cursor": "pointer"}),
                    dbc.Input(id="cfg-gantt-edge-hex", value="#000000", size="sm",
                              style={"borderRadius": "0 4px 4px 0",
                                     "fontFamily": "monospace", "width": "95px"}),
                ], className="d-flex"),
            ], width=3),
            dbc.Col([
                dbc.Label("Edge Width", className="small fw-semibold"),
                dbc.Input(id="cfg-gantt-edge-width", value=0.2, type="number",
                          min=0.0, max=5.0, step=0.1, size="sm"),
                html.Small("Points before responsive scaling", className="text-muted"),
            ], width=2),
        ], className="mb-3"),

        html.Hr(className="my-2"),

        # ── Test ID → Colour Mappings ────────────────────────────────────
        dbc.Row([
            dbc.Col(html.H6("🏷️ Test ID Colour Mappings", className="fw-bold text-success"),
                    width="auto"),
            dbc.Col(
                html.Small(
                    "Test IDs not listed here cycle through the Default Palette below.",
                    className="text-muted fst-italic",
                ),
                className="ms-2 d-flex align-items-center",
            ),
        ], align="center", className="mb-2"),

        html.Div(id="cfg-gantt-colors-container", children=[]),

        dbc.Button("➕ Add Test ID", id="btn-add-gantt-color", color="success",
                   size="sm", outline=True, className="mb-3 mt-1"),

        html.Hr(className="my-2"),

        # ── Default Palette ──────────────────────────────────────────────
        dbc.Row([
            dbc.Col(html.H6("🎨 Default Palette", className="fw-bold text-success"),
                    width="auto"),
            dbc.Col(
                html.Small(
                    "Colours assigned in order to unmapped Test IDs. Cycles when exhausted.",
                    className="text-muted fst-italic",
                ),
                className="ms-2 d-flex align-items-center",
            ),
        ], align="center", className="mb-2"),

        html.Div(id="cfg-gantt-palette-container", children=[]),

        dbc.Button("➕ Add Palette Colour", id="btn-add-palette-color", color="secondary",
                   size="sm", outline=True, className="mb-3 mt-1"),
    ])


def _series_row(idx: int, s: dict = None) -> dbc.Card:
    """Build one series card row for the editor."""
    s = s or {}
    i = idx
    color_val = s.get("line_color", "#1f77b4")

    return dbc.Card(className="mb-2 border-secondary", id=f"series-card-{i}", children=[
        dbc.CardHeader(
            dbc.Row([
                dbc.Col(html.B(f"Series {i + 1}", id=f"series-title-{i}",
                               className="small"), width="auto"),
                dbc.Col(
                    dbc.Button("✕ Remove", id={"type": "btn-remove-series", "index": i},
                               color="danger", size="sm", outline=True,
                               className="float-end"),
                    className="ms-auto", width="auto"
                ),
            ], align="center")
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label("Name", className="small fw-semibold"),
                    dbc.Input(id={"type": "series-name", "index": i},
                              value=s.get("name", ""), placeholder="e.g. P Avg A", size="sm"),
                ], width=3),
                dbc.Col([
                    dbc.Label("Value Column", className="small fw-semibold"),
                    dbc.Input(id={"type": "series-value-col", "index": i},
                              value=s.get("value_column", ""),
                              placeholder="e.g. PowerPfund_A_avg", size="sm"),
                ], width=3),
                dbc.Col([
                    dbc.Label("Keywords (comma-separated)", className="small fw-semibold"),
                    dbc.Input(id={"type": "series-keywords", "index": i},
                              value=", ".join(s.get("value_column_keywords", [])),
                              placeholder="e.g. PowerPfund_A_avg", size="sm"),
                ], width=4),
                dbc.Col([
                    dbc.Label("Alpha", className="small fw-semibold"),
                    dbc.Input(id={"type": "series-alpha", "index": i},
                              value=s.get("alpha", 0.65), type="number",
                              min=0.0, max=1.0, step=0.05, size="sm"),
                ], width=2),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Colour", className="small fw-semibold"),
                    html.Div([
                        dbc.Input(id={"type": "series-color-swatch", "index": i},
                                  type="color", value=color_val,
                                  style={"width": "38px", "height": "31px",
                                         "padding": "2px", "border": "1px solid #ced4da",
                                         "borderRadius": "4px 0 0 4px", "cursor": "pointer"}),
                        dbc.Input(id={"type": "series-color-hex", "index": i},
                                  value=color_val, placeholder="#rrggbb", size="sm",
                                  style={"borderRadius": "0 4px 4px 0",
                                         "fontFamily": "monospace", "width": "95px"}),
                    ], className="d-flex"),
                ], width=3),
                dbc.Col([
                    dbc.Label("Line Width", className="small fw-semibold"),
                    dbc.Input(id={"type": "series-linewidth", "index": i},
                              value=s.get("linewidth", 1.5), type="number",
                              min=0.5, max=10.0, step=0.5, size="sm"),
                ], width=2),
                dbc.Col([
                    dbc.Label("Line Style", className="small fw-semibold"),
                    dbc.Select(id={"type": "series-linestyle", "index": i},
                               options=[{"label": ls, "value": ls} for ls in LINESTYLES],
                               value=s.get("linestyle", "-"), size="sm"),
                ], width=2),
                dbc.Col([
                    dbc.Label("Marker", className="small fw-semibold"),
                    dbc.Select(id={"type": "series-marker", "index": i},
                               options=[{"label": m, "value": m} for m in MARKERS],
                               value=s.get("marker", "none"), size="sm"),
                ], width=2),
            ]),
        ], className="py-2"),
    ])


def _series_data_sections():
    """Series/chart/axis form elements for the chart editor modal (slim — aesthetics excluded)."""
    return [
        # ── Series ──────────────────────────────────────────────────────────
        dbc.Row([
            dbc.Col(html.H6("📈 Series", className="fw-bold text-primary"), width="auto"),
            dbc.Col(
                dbc.Row([
                    dbc.Col(
                        dbc.Select(id="cfg-palette-select",
                                   options=[{"label": k, "value": k}
                                            for k in COLOUR_PALETTES],
                                   placeholder="Apply colour palette…",
                                   size="sm"),
                        width=True,
                    ),
                    dbc.Col(
                        dbc.Button("Apply Palette", id="btn-apply-palette",
                                   color="info", size="sm", outline=True),
                        width="auto",
                    ),
                ], align="center", className="g-2"),
                className="ms-auto", width=6,
            ),
        ], align="center", className="mb-2"),

        html.Div(id="cfg-series-container", children=[]),

        dbc.Button("➕ Add Series", id="btn-add-series", color="secondary",
                   size="sm", outline=True, className="mb-3 mt-1"),

        dcc.Store(id="store-series-count", data=0),

        html.Hr(className="my-2"),

        # ── Chart ───────────────────────────────────────────────────────────
        dbc.Row([dbc.Col(html.H6("🖼️ Chart", className="fw-bold text-primary"))]),
        dbc.Row([
            dbc.Col([
                dbc.Label("Title", className="small fw-semibold"),
                dbc.Input(id="cfg-chart-title",
                          placeholder="e.g. Active Power Over Time", size="sm"),
            ], width=8),
        ], className="mb-3"),

        html.Hr(className="my-2"),

        # ── Axis ────────────────────────────────────────────────────────────
        dbc.Row([dbc.Col(html.H6("📐 Axis", className="fw-bold text-primary"))]),
        dbc.Row([
            dbc.Col([
                dbc.Label("X Label", className="small fw-semibold"),
                dbc.Input(id="cfg-x-label",
                          placeholder="e.g. Date & Time", size="sm"),
            ], width=3),
            dbc.Col([
                dbc.Label("Y Label", className="small fw-semibold"),
                dbc.Input(id="cfg-y-label",
                          placeholder="e.g. Active Power (kW)", size="sm"),
            ], width=3),
            dbc.Col([
                dbc.Label("Y Min", className="small fw-semibold"),
                dbc.Input(id="cfg-y-min", type="number",
                          placeholder="auto", size="sm"),
            ], width=2),
            dbc.Col([
                dbc.Label("Y Max", className="small fw-semibold"),
                dbc.Input(id="cfg-y-max", type="number",
                          placeholder="auto", size="sm"),
            ], width=2),
        ], className="mb-2"),
        dbc.Row([
            dbc.Col([
                dbc.Label("X Min (datetime or number)", className="small fw-semibold"),
                dbc.Input(id="cfg-x-min",
                          placeholder="e.g. 2026-01-24 12:00:00", size="sm"),
            ], width=4),
            dbc.Col([
                dbc.Label("X Max (datetime or number)", className="small fw-semibold"),
                dbc.Input(id="cfg-x-max",
                          placeholder="e.g. 2026-01-25 03:00:00", size="sm"),
            ], width=4),
        ], className="mb-2"),

        html.Small(
            "💡 Grid, resolution, fonts and legend are shared settings — edit them in the "
            "Aesthetics panel above.",
            className="text-muted fst-italic",
        ),
    ]


def _editor_modal_body():
    """Return the scrollable modal body — all config sections."""
    return [
        # ── Filename ────────────────────────────────────────────────────────
        dbc.Row([
            dbc.Col([
                dbc.Label("Filename (.json)", className="fw-semibold"),
                dbc.Input(id="cfg-filename",
                          placeholder="e.g. 0_config_composite_Active_Power.json",
                          size="sm"),
                html.Small("File will be saved to the selected config folder.",
                           className="text-muted"),
            ]),
        ], className="mb-3"),

        html.Hr(className="my-2"),

        # ── Config type badge + stores ───────────────────────────────────────
        html.Div(id="cfg-type-badge", className="mb-2"),
        dcc.Store(id="store-cfg-type", data=CFG_TYPE_SERIES),
        dcc.Store(id="store-gantt-color-count", data=0),
        dcc.Store(id="store-gantt-palette-count", data=0),

        html.Hr(className="my-2"),

        # ── Metadata ────────────────────────────────────────────────────────
        dbc.Row([dbc.Col(html.H6("📝 Metadata", className="fw-bold text-primary"))]),
        dbc.Row([
            dbc.Col([
                dbc.Label("Description", className="small fw-semibold"),
                dbc.Textarea(id="cfg-description", rows=2, size="sm",
                             placeholder="Brief description of this config…"),
            ], width=6),
            dbc.Col([
                dbc.Label("Usage Notes", className="small fw-semibold"),
                dbc.Textarea(id="cfg-usage", rows=2, size="sm",
                             placeholder="Usage instructions…"),
            ], width=6),
        ], className="mb-3"),

        html.Hr(className="my-2"),

        # ── Gantt section (visible when editing a gantt config) ──────────────
        dbc.Collapse(
            id="cfg-gantt-collapse",
            is_open=False,
            children=[_gantt_editor_section(), html.Hr(className="my-2")],
        ),

        # ── Series-data sections (collapsed when gantt config) ───────────────
        dbc.Collapse(
            id="cfg-series-sections-collapse",
            is_open=True,
            children=_series_data_sections(),
        ),
    ]


def _editor_modal():
    return dbc.Modal(
        id="cfg-editor-modal", size="xl", scrollable=True, is_open=False,
        children=[
            dbc.ModalHeader(dbc.ModalTitle(id="cfg-editor-title", children="New Config")),
            dbc.ModalBody(_editor_modal_body()),
            dbc.ModalFooter([
                html.Div(id="cfg-save-status", className="me-auto small"),
                dbc.Button("💾 Save", id="btn-cfg-save",   color="primary",   className="me-2"),
                dbc.Button("Cancel",  id="btn-cfg-cancel", color="secondary"),
            ]),
        ],
    )


def _confirm_delete_modal():
    return dbc.Modal(id="cfg-confirm-delete-modal", is_open=False, children=[
        dbc.ModalHeader(dbc.ModalTitle("Confirm Delete")),
        dbc.ModalBody(html.P(id="cfg-delete-confirm-text",
                             children="Are you sure you want to delete this file?")),
        dbc.ModalFooter([
            dbc.Button("🗑️ Delete", id="btn-cfg-confirm-delete",
                       color="danger",    className="me-2"),
            dbc.Button("Cancel",    id="btn-cfg-cancel-delete",
                       color="secondary"),
        ]),
    ])


def _batch_profile_item(idx: int, filename: str, included: bool) -> dbc.Card:
    """Build one sortable row for the Batch Profile list."""
    badge_color = "primary" if included else "secondary"
    label_style = {
        "fontFamily": "monospace",
        "wordBreak":  "break-all",
        "opacity":    "1.0" if included else "0.45",
    }
    return dbc.Card(
        id={"type": "bp-item-card", "index": idx},
        className="mb-1 border-secondary",
        children=[
            dbc.CardBody(
                dbc.Row([
                    # Rank badge
                    dbc.Col(
                        dbc.Badge(
                            str(idx + 1),
                            id={"type": "bp-rank-badge", "index": idx},
                            color=badge_color,
                            style={"minWidth": "26px", "textAlign": "center"},
                        ),
                        width="auto", className="d-flex align-items-center",
                    ),
                    # Filename label
                    dbc.Col(
                        html.Span(
                            filename,
                            id={"type": "bp-item-label", "index": idx},
                            className="small",
                            style=label_style,
                        ),
                        className="d-flex align-items-center",
                    ),
                    # Include / Exclude toggle
                    dbc.Col(
                        dbc.Switch(
                            id={"type": "bp-item-switch", "index": idx},
                            value=included,
                            label="",
                            className="mb-0",
                        ),
                        width="auto",
                        className="d-flex align-items-center",
                    ),
                    # Up / Down buttons
                    dbc.Col(
                        html.Div([
                            dbc.Button(
                                "▲", size="sm", color="light",
                                id={"type": "bp-btn-up",   "index": idx},
                                className="py-0 px-1 me-1 border",
                                style={"lineHeight": "1.4", "fontSize": "11px"},
                            ),
                            dbc.Button(
                                "▼", size="sm", color="light",
                                id={"type": "bp-btn-down", "index": idx},
                                className="py-0 px-1 border",
                                style={"lineHeight": "1.4", "fontSize": "11px"},
                            ),
                        ], className="d-flex"),
                        width="auto", className="d-flex align-items-center",
                    ),
                ], align="center", className="g-2"),
                className="py-1 px-2",
            ),
        ],
    )


def _batch_profile_card():
    """Return the Batch Profile dbc.Card for the Config Manager tab."""
    return dbc.Card(className="mb-3", children=[
        dbc.CardHeader(dbc.Row([
            dbc.Col(html.B("📋 Batch Profile"), width="auto"),
            dbc.Col(
                html.Small(
                    "Choose which configs run during a batch job and set their order.",
                    className="text-muted",
                ),
                className="d-flex align-items-center ms-2",
            ),
            dbc.Col(html.Div([
                dbc.Button(
                    "💾 Save Profile", id="btn-bp-save",
                    color="primary", size="sm", className="me-1",
                ),
                dbc.Button(
                    "↺ Reset to Default", id="btn-bp-reset",
                    color="secondary", size="sm", outline=True,
                ),
            ], className="d-flex"), className="ms-auto", width="auto"),
        ], align="center", justify="between")),

        dbc.CardBody([
            # Status / save feedback
            html.Div(id="bp-status", className="mb-2 small"),

            # Summary bar — shows counts + colour-coded file badges
            html.Div(
                id="bp-summary-bar",
                className="mb-2",
                children=html.Small(
                    "Load a config folder above to build the profile.",
                    className="text-muted",
                ),
            ),

            # Sortable list (▲▼ buttons only — no drag-and-drop)
            html.Div(
                id="bp-item-list",
                style={"maxHeight": "360px", "overflowY": "auto"},
                children=[
                    html.P("No folder loaded.", className="text-muted small mb-0"),
                ],
            ),

            html.Hr(className="my-2"),

            # Numbered run-order preview
            html.Div([
                html.B("Run order: ", className="small"),
                html.Span(
                    id="bp-order-preview",
                    className="small text-muted",
                    children="—",
                ),
            ]),

            # Hidden stores
            dcc.Store(id="store-bp-order",  data=[]),  # list of {filename, included}
            dcc.Store(id="store-bp-folder", data=""),  # folder that was last loaded
        ]),
    ])


def _aesthetics_card():
    """Dedicated inline editor card for aesthetics.json — always visible in Config Manager."""
    return dbc.Card(className="mb-3 border-warning", children=[
        dbc.CardHeader(dbc.Row([
            dbc.Col(html.B("🎨 Aesthetics"), width="auto"),
            dbc.Col(
                html.Small(
                    "Shared visual settings for all charts — fonts, resolution, grid, legend. "
                    "Saved to aesthetics.json in the config folder.",
                    className="text-muted",
                ),
                className="d-flex align-items-center ms-2",
            ),
            dbc.Col(
                dbc.Button("💾 Save aesthetics.json", id="btn-aes-save",
                           color="warning", size="sm"),
                className="ms-auto", width="auto",
            ),
        ], align="center", justify="between")),

        dbc.CardBody([
            html.Div(id="aes-load-status", className="mb-2 small"),
            html.Div(id="aes-save-status", className="mb-2 small"),

            # ── Font ────────────────────────────────────────────────────
            dbc.Row([dbc.Col(html.H6("🔤 Font", className="fw-bold text-warning"))]),
            dbc.Row([
                dbc.Col([dbc.Label("Family", className="small fw-semibold"),
                         dbc.Input(id="aes-font-family", value="sans-serif", size="sm")], width=3),
                dbc.Col([dbc.Label("Title Size", className="small fw-semibold"),
                         dbc.Input(id="aes-title-fs", value=20, type="number",
                                   min=6, max=72, size="sm")], width=2),
                dbc.Col([dbc.Label("Axis Label Size", className="small fw-semibold"),
                         dbc.Input(id="aes-axis-fs", value=15, type="number",
                                   min=6, max=48, size="sm")], width=2),
                dbc.Col([dbc.Label("Tick Size", className="small fw-semibold"),
                         dbc.Input(id="aes-tick-fs", value=12, type="number",
                                   min=6, max=36, size="sm")], width=2),
                dbc.Col([dbc.Label("Legend Size", className="small fw-semibold"),
                         dbc.Input(id="aes-legend-fs", value=13, type="number",
                                   min=6, max=36, size="sm")], width=2),
                dbc.Col([dbc.Label("Scale ×", className="small fw-semibold"),
                         dbc.Input(id="aes-font-scale", value=1.0, type="number",
                                   min=0.5, max=3.0, step=0.1, size="sm")], width=1),
            ], className="mb-3"),

            html.Hr(className="my-2"),

            # ── Chart / Export ──────────────────────────────────────────
            dbc.Row([dbc.Col(html.H6("🖼️ Chart / Export", className="fw-bold text-warning"))]),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Background Colour", className="small fw-semibold"),
                    html.Div([
                        dbc.Input(id="aes-bg-color-swatch", type="color", value="#ffffff",
                                  style={"width": "38px", "height": "31px", "padding": "2px",
                                         "border": "1px solid #ced4da",
                                         "borderRadius": "4px 0 0 4px", "cursor": "pointer"}),
                        dbc.Input(id="aes-bg-color-hex", value="#ffffff", size="sm",
                                  style={"borderRadius": "0 4px 4px 0",
                                         "fontFamily": "monospace", "width": "95px"}),
                    ], className="d-flex"),
                ], width=3),
                dbc.Col([dbc.Label("Width (px)", className="small fw-semibold"),
                         dbc.Input(id="aes-res-w", value=2560, type="number",
                                   min=320, size="sm")], width=2),
                dbc.Col([dbc.Label("Height (px)", className="small fw-semibold"),
                         dbc.Input(id="aes-res-h", value=1440, type="number",
                                   min=240, size="sm")], width=2),
                dbc.Col([dbc.Label("DPI", className="small fw-semibold"),
                         dbc.Input(id="aes-dpi", value=96, type="number",
                                   min=72, max=600, size="sm")], width=2),
                dbc.Col([dbc.Label("LW Scale ×", className="small fw-semibold"),
                         dbc.Input(id="aes-lw-scale", value=1.0, type="number",
                                   min=0.5, max=3.0, step=0.1, size="sm")], width=2),
            ], className="mb-3"),

            html.Hr(className="my-2"),

            # ── Grid ────────────────────────────────────────────────────
            dbc.Row([dbc.Col(html.H6("🔲 Grid", className="fw-bold text-warning"))]),
            dbc.Row([
                dbc.Col([dbc.Label("Visible", className="small fw-semibold"),
                         dbc.Select(id="aes-grid-visible",
                                    options=[{"label": "Yes", "value": "true"},
                                             {"label": "No",  "value": "false"}],
                                    value="true", size="sm")], width=2),
                dbc.Col([dbc.Label("Axis", className="small fw-semibold"),
                         dbc.Select(id="aes-grid-axis",
                                    options=[{"label": a, "value": a}
                                             for a in ["both", "x", "y"]],
                                    value="both", size="sm")], width=2),
                dbc.Col([dbc.Label("Line Style", className="small fw-semibold"),
                         dbc.Select(id="aes-grid-linestyle",
                                    options=[{"label": ls, "value": ls} for ls in LINESTYLES],
                                    value="-", size="sm")], width=2),
                dbc.Col([dbc.Label("Alpha", className="small fw-semibold"),
                         dbc.Input(id="aes-grid-alpha", value=0.3, type="number",
                                   min=0.0, max=1.0, step=0.05, size="sm")], width=2),
                dbc.Col([dbc.Label("Width", className="small fw-semibold"),
                         dbc.Input(id="aes-grid-width", value=1.0, type="number",
                                   min=0.5, max=5.0, step=0.5, size="sm")], width=1),
                dbc.Col([
                    dbc.Label("Colour", className="small fw-semibold"),
                    html.Div([
                        dbc.Input(id="aes-grid-color-swatch", type="color", value="#505050",
                                  style={"width": "38px", "height": "31px", "padding": "2px",
                                         "border": "1px solid #ced4da",
                                         "borderRadius": "4px 0 0 4px", "cursor": "pointer"}),
                        dbc.Input(id="aes-grid-color-hex", value="#505050", size="sm",
                                  style={"borderRadius": "0 4px 4px 0",
                                         "fontFamily": "monospace", "width": "95px"}),
                    ], className="d-flex"),
                ], width=3),
            ], className="mb-3"),

            html.Hr(className="my-2"),

            # ── Legend & Subplot ────────────────────────────────────────
            dbc.Row([dbc.Col(html.H6("📦 Legend & Subplot", className="fw-bold text-warning"))]),
            dbc.Row([
                dbc.Col([dbc.Label("Wrap Width (chars)", className="small fw-semibold"),
                         dbc.Input(id="aes-legend-wrap-w", value=28, type="number",
                                   min=10, max=80, size="sm")], width=2),
                dbc.Col([dbc.Label("Pad Top", className="small fw-semibold"),
                         dbc.Input(id="aes-pad-top", value=0.5, type="number",
                                   min=0.0, max=5.0, step=0.1, size="sm")], width=2),
                dbc.Col([dbc.Label("Sep Above", className="small fw-semibold"),
                         dbc.Input(id="aes-pad-sep-above", value=0.4, type="number",
                                   min=0.0, max=5.0, step=0.1, size="sm")], width=2),
                dbc.Col([dbc.Label("Sep Below", className="small fw-semibold"),
                         dbc.Input(id="aes-pad-sep-below", value=0.4, type="number",
                                   min=0.0, max=5.0, step=0.1, size="sm")], width=2),
                dbc.Col([dbc.Label("Gap Slots", className="small fw-semibold"),
                         dbc.Input(id="aes-gap-slots", value=0.5, type="number",
                                   min=0.0, max=5.0, step=0.1, size="sm")], width=2),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([dbc.Label("Left",     className="small fw-semibold"),
                         dbc.Input(id="aes-sp-left",   value=0.03, type="number",
                                   min=0.0, max=0.5, step=0.01, size="sm")], width=2),
                dbc.Col([dbc.Label("Right",    className="small fw-semibold"),
                         dbc.Input(id="aes-sp-right",  value=0.92, type="number",
                                   min=0.5, max=1.0, step=0.01, size="sm")], width=2),
                dbc.Col([dbc.Label("Top",      className="small fw-semibold"),
                         dbc.Input(id="aes-sp-top",    value=0.95, type="number",
                                   min=0.5, max=1.0, step=0.01, size="sm")], width=2),
                dbc.Col([dbc.Label("Bottom",   className="small fw-semibold"),
                         dbc.Input(id="aes-sp-bottom", value=0.06, type="number",
                                   min=0.0, max=0.5, step=0.01, size="sm")], width=2),
                dbc.Col([dbc.Label("Legend X", className="small fw-semibold"),
                         dbc.Input(id="aes-sp-lgx",    value=0.92, type="number",
                                   min=0.0, max=1.5, step=0.01, size="sm")], width=2),
                dbc.Col([dbc.Label("Legend Y", className="small fw-semibold"),
                         dbc.Input(id="aes-sp-lgy",    value=0.83, type="number",
                                   min=0.0, max=1.5, step=0.01, size="sm")], width=2),
            ], className="mb-2"),
        ]),
    ])



def config_manager_tab():
    """Return the ⚙️ Config Manager dbc.Tab."""
    return dbc.Tab(label="⚙️ Config Manager", tab_id="tab-config-manager", children=[
        dbc.Container(fluid=True, children=[

            # ── Folder selector ──────────────────────────────────────────
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(html.B("Config Folder")),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col(dbc.Label("Folder Path:"), width=2),
                        dbc.Col(
                            dbc.Input(id="cfgmgr-folder-path",
                                      placeholder="e.g. 5_configs/  or  C:\\my_configs",
                                      size="sm"),
                            width=True,
                        ),
                        dbc.Col(html.Div([
                            dbc.Button("📁 Browse", id="btn-cfgmgr-browse",
                                       color="secondary", size="sm", className="me-1"),
                        ], className="d-flex align-items-center"), width="auto"),
                        dbc.Col(
                            dbc.Button("🔄 Refresh", id="btn-cfgmgr-refresh",
                                       color="info", size="sm", outline=True),
                            width="auto",
                        ),
                    ], className="mb-2 align-items-center"),
                    html.Div(id="cfgmgr-folder-status", className="text-muted small"),
                ]),
            ]),

            # ── Batch Profile ────────────────────────────────────────────
            _batch_profile_card(),

            # ── Aesthetics ───────────────────────────────────────────────
            _aesthetics_card(),

            # ── File list + action toolbar ───────────────────────────────
            dbc.Card(className="mb-3", children=[
                dbc.CardHeader(dbc.Row([
                    dbc.Col(html.B("Config Files"), width="auto"),
                    dbc.Col(html.Div([
                        dbc.Button("➕ New",       id="btn-cfgmgr-new",
                                   color="primary",   size="sm", className="me-1"),
                        dbc.Button("✏️ Edit",      id="btn-cfgmgr-edit",
                                   color="secondary", size="sm",
                                   className="me-1", disabled=True),
                        dbc.Button("📋 Clone",     id="btn-cfgmgr-clone",
                                   color="info",      size="sm", outline=True,
                                   className="me-1",  disabled=True),
                        dbc.Button("🗑️ Delete",    id="btn-cfgmgr-delete",
                                   color="danger",    size="sm", outline=True,
                                   disabled=True),
                    ], className="d-flex"), className="ms-auto", width="auto"),
                ], align="center", justify="between")),
                dbc.CardBody([
                    html.Div(id="cfgmgr-action-status", className="mb-2 small"),
                    html.Div(
                        id="cfgmgr-file-list",
                        style={"maxHeight": "380px", "overflowY": "auto"},
                        children=[
                            html.P("No folder loaded. Set a folder path above and click Refresh.",
                                   className="text-muted small"),
                        ],
                    ),
                ]),
            ]),

            # Stores
            dcc.Store(id="store-cfgmgr-selected",  data=None),
            dcc.Store(id="store-cfgmgr-edit-mode", data=None),

            _editor_modal(),
            _confirm_delete_modal(),
        ]),
    ])