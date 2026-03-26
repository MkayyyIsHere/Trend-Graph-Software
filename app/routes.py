"""app/routes.py — Flask file/folder picker endpoints via a Tkinter dispatcher thread."""
import queue
import threading

from flask import jsonify, request as flask_request

# ── File-type maps for the OS dialog ────────────────────────────────────────
_EXT_MAP = {
    'json':   [('JSON', '*.json'), ('All', '*.*')],
    'csv':    [('CSV/TXT', '*.csv *.txt'), ('CSV', '*.csv'), ('TXT', '*.txt'), ('All', '*.*')],
    'data':   [('Tab/CSV', '*.txt *.csv'), ('All', '*.*')],
    'png':    [('Image', '*.png *.jpg'), ('All', '*.*')],
    'pptx':   [('PowerPoint', '*.pptx'), ('All', '*.*')],
    'export': [('PNG', '*.png'), ('PDF', '*.pdf'), ('SVG', '*.svg'), ('All', '*.*')],
}
_TITLE_MAP = {
    'json':   'Select JSON Config File',
    'csv':    'Select Event / Task CSV',
    'data':   'Select Series Data File',
    'png':    'Select Image Folder File',
    'pptx':   'Select PowerPoint Template',
    'export': 'Save Chart As…',
}
_DEFAULT_EXT_MAP = {'export': '.png', 'pptx': '.pptx'}


class TkDialogDispatcher:
    """
    Single Tkinter dispatcher thread that owns the Tk root for its whole lifetime.
    Flask routes submit jobs via a Queue and block on a threading.Event until done.
    This is necessary because Tkinter is not thread-safe — dialogs must run on the
    thread that created the Tk root.
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._run, name='TkDialogDispatcher', daemon=True)
        t.start()

    def _run(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            # Headless / non-GUI env — drain queue, return empty paths
            while True:
                try:
                    job = self._queue.get(timeout=1)
                    if job is None:
                        break
                    job['result'].append('')
                    job['done'].set()
                except Exception:
                    pass
            return

        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        while True:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                root.update_idletasks()
                continue

            if job is None:
                break

            try:
                root.deiconify()
                root.lift()
                root.focus_force()
                root.update()

                if job['mode'] == 'file' and job.get('save'):
                    path = filedialog.asksaveasfilename(
                        parent=root, title=job['title'],
                        defaultextension=job.get('default_ext', ''),
                        filetypes=job.get('filetypes') or [('All', '*.*')])
                elif job['mode'] == 'file':
                    path = filedialog.askopenfilename(
                        parent=root, title=job['title'],
                        filetypes=job.get('filetypes') or [('All', '*.*')])
                else:
                    path = filedialog.askdirectory(parent=root, title=job['title'])

                job['result'].append(path or '')
            except Exception:
                job['result'].append('')
            finally:
                root.withdraw()
                job['done'].set()

    def pick(self, mode: str, title: str, filetypes=None,
             save: bool = False, default_ext: str = '') -> str:
        """Submit a dialog job and block until the user responds (or times out)."""
        result_box = []
        done_event = threading.Event()
        self._queue.put({
            'mode': mode, 'title': title, 'filetypes': filetypes,
            'save': save, 'default_ext': default_ext,
            'result': result_box, 'done': done_event,
        })
        done_event.wait(timeout=120)
        return result_box[0] if result_box else ''


def register_routes(server, dispatcher: TkDialogDispatcher):
    """Register /api/pick-file and /api/pick-folder on the Flask server."""

    @server.route('/api/pick-file')
    def pick_file():
        kind = flask_request.args.get('kind', 'json')
        save = flask_request.args.get('save', 'false').lower() == 'true'
        path = dispatcher.pick(
            mode='file',
            title=_TITLE_MAP.get(kind, 'Select File'),
            filetypes=_EXT_MAP.get(kind, [('All', '*.*')]),
            save=save,
            default_ext=_DEFAULT_EXT_MAP.get(kind, ''),
        )
        return jsonify({'path': path})

    @server.route('/api/pick-folder')
    def pick_folder():
        title = flask_request.args.get('title', 'Select Folder')
        path  = dispatcher.pick(mode='folder', title=title)
        return jsonify({'path': path})