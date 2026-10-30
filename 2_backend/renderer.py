# =============================================================================
# PNG RENDERER — one headless browser (kaleido) shared by a whole batch
#
# Why not kaleido.start_sync_server(): its worker thread dies on the first
# failed render (CancelledError escapes its loop) and every later call then
# blocks forever; its call_function() also isn't safe across threads. Here
# calls are serialised, time out, and the browser is restarted after a
# failure, so one bad chart can never stall a batch. The PNG file is written
# by us, not kaleido, so a locked output file is a normal per-chart error.
# =============================================================================

import asyncio
import os
import threading

import kaleido

# MathJax off: charts use no LaTeX, and kaleido would otherwise fetch it from
# a CDN on each render (slow or failing on offline / proxied PCs).
# plotly.js comes from the local plotly package.
KALEIDO_OPTS = {'mathjax': False}

_RENDER_TIMEOUT = 120     # seconds per chart before the browser is restarted
_OPEN_TIMEOUT   = 120


class RenderError(Exception):
    """A chart could not be rendered or saved (message is user-facing)."""


class PngRenderer:
    """Render Plotly figures to PNG with one long-lived browser.

    Usage:
        with PngRenderer() as r:
            r.save(fig, path, width, height)     # or r.png(fig, width, height)
    """

    def __init__(self):
        self._loop   = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._lock   = threading.Lock()
        self._k      = None
        self._open()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def _call(self, coro, timeout):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _open(self):
        async def _start():
            k = kaleido.Kaleido(**KALEIDO_OPTS)
            await k.open()
            return k
        self._k = self._call(_start(), _OPEN_TIMEOUT)

    def _close_browser(self):
        k, self._k = self._k, None
        if k is not None:
            try:
                self._call(k.close(), 30)
            except BaseException:   # noqa: BLE001 — best effort; it may already be dead
                pass

    def close(self):
        self._close_browser()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── rendering ────────────────────────────────────────────────────────────
    def png(self, fig, width: int, height: int) -> bytes:
        """PNG bytes for *fig*. Raises RenderError; the browser is restarted
        after a failure so the next chart starts clean."""
        opts = {'format': 'png', 'width': width, 'height': height, 'scale': 1}
        with self._lock:
            if self._k is None:
                self._open()
            try:
                return self._call(self._k.calc_fig(fig, opts=opts), _RENDER_TIMEOUT)
            except BaseException as e:   # noqa: BLE001 — includes CancelledError / TimeoutError
                self._close_browser()
                what = "timed out" if isinstance(e, TimeoutError) else (str(e) or type(e).__name__)
                raise RenderError(f"image rendering failed ({what})") from None

    def save(self, fig, path: str, width: int, height: int) -> None:
        """Render and write *path* (via a temp file, so a failed write never
        leaves a half-written PNG)."""
        data = self.png(fig, width, height)
        tmp  = f"{path}.part"
        try:
            with open(tmp, 'wb') as fh:
                fh.write(data)
            os.replace(tmp, path)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise RenderError(
                "could not save — the file may be open in another program (image "
                "viewer, PowerPoint, OneDrive sync). Close it and run again. "
                f"[{e.strerror or e}]") from None


def render_png(fig, width: int, height: int) -> bytes:
    """One-off PNG render (single-chart tab)."""
    with PngRenderer() as r:
        return r.png(fig, width, height)
