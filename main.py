import argparse

from utils.constants import DASH_PORT
from app.dash_app import DashApp


def main():
    parser = argparse.ArgumentParser(
        description='Composite Data & Gantt Plotter — Dash Edition'
    )
    parser.add_argument('--port',       type=int,            default=DASH_PORT,
                        help=f'Port to serve on (default: {DASH_PORT})')
    parser.add_argument('--debug',      action='store_true', default=False,
                        help='Enable Dash debug / hot-reload mode')
    parser.add_argument('--no-browser', action='store_true', default=False,
                        help='Do not auto-open a browser tab on startup')
    args = parser.parse_args()

    DashApp().run(port=args.port, debug=args.debug, auto_open=not args.no_browser)


if __name__ == '__main__':
    main()