"""1_app/dash_app.py — DashApp orchestrator: wires layout, callbacks, and routes."""
import os
import tempfile

import dash
import dash_bootstrap_components as dbc

from utils.constants import DASH_HOST, DASH_PORT
from app.state import AppState
from app.layout import build_layout, ensure_assets
from app.callbacks import register_callbacks
from app.routes import TkDialogDispatcher, register_routes

try:
    from pptx import Presentation  # noqa: F401
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False


class DashApp:
    """
    Thin orchestrator — owns the Dash instance and wires together:
      • AppState   (shared mutable state / 2_backend objects)
      • layout.py  (all HTML / Dash component trees)
      • callbacks.py (all @1_app.callback registrations)
      • routes.py  (Flask file/folder picker endpoints + Tkinter dispatcher)
    """

    def __init__(self):
        self._state    = AppState()
        self._temp_dir = tempfile.mkdtemp(prefix='composite_plotter_')
        self._dispatcher = TkDialogDispatcher()

        ensure_assets()

        self._app = dash.Dash(
            __name__,
            assets_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '4_assets'),
            external_stylesheets=[dbc.themes.FLATLY],
            title='Composite Data Plotter',
            suppress_callback_exceptions=True,
        )
        # Callable layout → rebuilt per page load, so remembered settings are current.
        self._app.layout = build_layout

        register_callbacks(self._app, self._state, self._temp_dir)
        register_routes(self._app.server, self._dispatcher)

    # ── Public run method ────────────────────────────────────────────────────

    def run(self, port: int = DASH_PORT, debug: bool = False, auto_open: bool = True):
        import webbrowser
        from threading import Timer

        print("=" * 60)
        print("  COMPOSITE DATA & GANTT PLOTTER — Dash Edition")
        print("=" * 60)
        print(f"  URL         : http://{DASH_HOST}:{port}")
        print(f"  python-pptx : {'available' if _PPTX_AVAILABLE else 'NOT INSTALLED'}")
        print("=" * 60)

        if auto_open:
            Timer(1.5, lambda: webbrowser.open(f"http://{DASH_HOST}:{port}")).start()

        self._app.run(debug=debug, port=port, host=DASH_HOST)