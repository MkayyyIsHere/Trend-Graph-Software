"""1_app/batch_profile_callbacks.py — Callbacks for the 📋 Batch Profile card.

Registration
------------
Call ``register_batch_profile_callbacks(app, state)`` from inside
``register_callbacks()`` in ``1_app/callbacks.py``, just before (or after)
the existing ``register_config_manager_callbacks(app, state)`` call:

    from app.batch_profile_callbacks import register_batch_profile_callbacks
    ...
    register_batch_profile_callbacks(app, state)
    register_config_manager_callbacks(app, state)
"""

from __future__ import annotations

import os

from dash import Input, Output, State, ctx, html, no_update, ALL
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from app.config_manager_layout import _batch_profile_item
from backend.batch_profile import BatchProfileManager, BATCH_PROFILE_FILENAME


# ── Module-level manager (one per server process) ─────────────────────────
_bp_manager = BatchProfileManager()


# ── Helpers ───────────────────────────────────────────────────────────────

def _render_items(order: list[dict]) -> list:
    """Render the full sortable list from ``store-bp-order`` data."""
    if not order:
        return [html.P("No JSON configs found in this folder.",
                       className="text-muted small mb-0")]
    return [_batch_profile_item(i, row["filename"], row["included"])
            for i, row in enumerate(order)]


def _summary_bar(order: list[dict]) -> list:
    """Return summary badges: total / included count + file chips."""
    if not order:
        return [html.Small("No configs.", className="text-muted")]
    included = [r for r in order if r["included"]]
    n_total  = len(order)
    n_inc    = len(included)
    badges   = [
        dbc.Badge(f"{n_inc} / {n_total} selected",
                  color="primary" if n_inc else "secondary",
                  className="me-2"),
    ]
    for r in included:
        short = r["filename"].replace("_config_composite_", " ").replace(".json", "").strip()
        badges.append(
            dbc.Badge(short, color="light",
                      text_color="dark",
                      className="me-1 border",
                      style={"fontFamily": "monospace", "fontSize": "10px"}),
        )
    return badges


def _order_preview(order: list[dict]) -> str:
    """Build the numbered run-order preview string."""
    included = [r["filename"] for r in order if r["included"]]
    if not included:
        return "No configs selected."
    parts = []
    for i, fname in enumerate(included, 1):
        short = fname.replace("_config_composite_", " ").replace(".json", "").strip()
        parts.append(f"{i}. {short}")
    return "  →  ".join(parts)


def _move(order: list[dict], idx: int, direction: int) -> list[dict]:
    """Move item at *idx* up (-1) or down (+1), return updated list."""
    order = list(order)
    target = idx + direction
    if 0 <= target < len(order):
        order[idx], order[target] = order[target], order[idx]
    return order


# ── Registration ──────────────────────────────────────────────────────────

def register_batch_profile_callbacks(app, state):
    """Register all Batch Profile callbacks."""

    # ── 1. Load / refresh the profile when the folder changes ────────────
    @app.callback(
        Output("store-bp-order",  "data"),
        Output("store-bp-folder", "data"),
        Output("bp-item-list",    "children"),
        Output("bp-summary-bar",  "children"),
        Output("bp-order-preview","children"),
        Output("bp-status",       "children"),
        Input("cfgmgr-folder-path", "value"),
        Input("btn-cfgmgr-refresh", "n_clicks"),
        prevent_initial_call=True,
    )
    def load_profile(folder, _refresh):
        if not folder or not folder.strip():
            empty = [html.P("Enter a folder path above.",
                            className="text-muted small mb-0")]
            return [], "", empty, [], "—", ""

        folder = folder.strip()
        if not os.path.isdir(folder):
            msg = [html.P("Folder not found.", className="text-danger small mb-0")]
            return [], folder, msg, [], "—", ""

        # Load (or initialise) the profile for this folder
        _bp_manager.load(folder)
        order = _bp_manager.merge_with_folder(folder)

        profile_path = os.path.join(folder, BATCH_PROFILE_FILENAME)
        if os.path.isfile(profile_path):
            status = dbc.Alert(
                f"✓ Profile loaded from {BATCH_PROFILE_FILENAME}",
                color="success", className="py-1 mb-0",
            )
        else:
            status = dbc.Alert(
                "ℹ No saved profile found — showing all configs in alphabetical order. "
                "Reorder below and click 💾 Save Profile.",
                color="info", className="py-1 mb-0",
            )

        return (
            order,
            folder,
            _render_items(order),
            _summary_bar(order),
            _order_preview(order),
            status,
        )

    # ── 2. Up / Down buttons ─────────────────────────────────────────────
    @app.callback(
        Output("store-bp-order",   "data",     allow_duplicate=True),
        Output("bp-item-list",     "children", allow_duplicate=True),
        Output("bp-summary-bar",   "children", allow_duplicate=True),
        Output("bp-order-preview", "children", allow_duplicate=True),
        Input({"type": "bp-btn-up",   "index": ALL}, "n_clicks"),
        Input({"type": "bp-btn-down", "index": ALL}, "n_clicks"),
        State("store-bp-order", "data"),
        prevent_initial_call=True,
    )
    def move_item(up_clicks, down_clicks, order):
        if not order:
            raise PreventUpdate

        triggered = ctx.triggered_id
        if not triggered:
            raise PreventUpdate

        idx       = triggered["index"]
        direction = -1 if triggered["type"] == "bp-btn-up" else 1
        new_order = _move(order, idx, direction)

        return (
            new_order,
            _render_items(new_order),
            _summary_bar(new_order),
            _order_preview(new_order),
        )

    # ── 3. Include / Exclude switch ───────────────────────────────────────
    @app.callback(
        Output("store-bp-order",   "data",     allow_duplicate=True),
        Output("bp-item-list",     "children", allow_duplicate=True),
        Output("bp-summary-bar",   "children", allow_duplicate=True),
        Output("bp-order-preview", "children", allow_duplicate=True),
        Input({"type": "bp-item-switch", "index": ALL}, "value"),
        State("store-bp-order", "data"),
        prevent_initial_call=True,
    )
    def toggle_include(switch_values, order):
        if not order or not switch_values:
            raise PreventUpdate

        new_order = [
            {"filename": row["filename"], "included": bool(sw)}
            for row, sw in zip(order, switch_values)
        ]

        return (
            new_order,
            _render_items(new_order),
            _summary_bar(new_order),
            _order_preview(new_order),
        )

    # ── 4. Save Profile button ────────────────────────────────────────────
    @app.callback(
        Output("bp-status", "children", allow_duplicate=True),
        Input("btn-bp-save",     "n_clicks"),
        State("store-bp-order",  "data"),
        State("store-bp-folder", "data"),
        prevent_initial_call=True,
    )
    def save_profile(_, order, folder):
        if not folder or not os.path.isdir(folder):
            return dbc.Alert("❌ No valid folder loaded.", color="danger",
                             className="py-1 mb-0")
        if not order:
            return dbc.Alert("❌ No configs to save.", color="warning",
                             className="py-1 mb-0")

        included_names = [r["filename"] for r in order if r["included"]]
        if _bp_manager.save(folder, included_names):
            n = len(included_names)
            return dbc.Alert(
                f"✓ Profile saved — {n} config(s) in run order "
                f"({BATCH_PROFILE_FILENAME})",
                color="success", className="py-1 mb-0",
            )
        return dbc.Alert("❌ Failed to save profile — check folder permissions.",
                         color="danger", className="py-1 mb-0")

    # ── 5. Reset to alphabetical ──────────────────────────────────────────
    @app.callback(
        Output("store-bp-order",   "data",     allow_duplicate=True),
        Output("bp-item-list",     "children", allow_duplicate=True),
        Output("bp-summary-bar",   "children", allow_duplicate=True),
        Output("bp-order-preview", "children", allow_duplicate=True),
        Output("bp-status",        "children", allow_duplicate=True),
        Input("btn-bp-reset",      "n_clicks"),
        State("store-bp-folder",   "data"),
        prevent_initial_call=True,
    )
    def reset_to_alpha(_, folder):
        if not folder or not os.path.isdir(folder):
            raise PreventUpdate

        # Rebuild from scratch — all files included, alpha order
        all_json = sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith(".json") and f != BATCH_PROFILE_FILENAME
        )
        order = [{"filename": f, "included": True} for f in all_json]

        status = dbc.Alert(
            "↺ Reset to alphabetical order. Click 💾 Save Profile to persist.",
            color="info", className="py-1 mb-0",
        )
        return (
            order,
            _render_items(order),
            _summary_bar(order),
            _order_preview(order),
            status,
        )