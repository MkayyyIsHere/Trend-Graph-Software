"""1_app/routes.py — Flask file/folder picker endpoints.

Uses the Windows native Win32 API via ctypes so that dialogs always appear on
top regardless of whether the app is running as a PyInstaller .exe or from
source. Tkinter is NOT used — it cannot reliably claim foreground focus when
called from a background thread inside a frozen executable.

Falls back to tkinter on non-Windows platforms (Linux/macOS dev machines).
"""
import sys
import threading
import queue
import traceback

from flask import jsonify, request as flask_request

# ── File-type maps ────────────────────────────────────────────────────────────
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
    'png':    'Select Image File',
    'pptx':   'Select PowerPoint Template',
    'export': 'Save Chart As…',
}
_DEFAULT_EXT_MAP = {'export': '.png', 'pptx': '.pptx'}


# ── Windows native pickers (ctypes) ──────────────────────────────────────────

def _get_foreground_hwnd():
    import ctypes, ctypes.wintypes, os
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd:
        return hwnd
    pid = os.getpid()
    found = ctypes.wintypes.HWND(0)
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _cb(hwnd, _):
        lp_pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lp_pid))
        if lp_pid.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            found.value = hwnd
            return False
        return True
    ctypes.windll.user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return found.value or 0


def _win_pick_folder(title: str) -> str:
    import ctypes, ctypes.wintypes
    ole32   = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    print(f"[PICKER] _win_pick_folder called: title={title!r}", flush=True)

    ole32.CoInitialize(None)
    try:
        CLSID_FileOpenDialog = '{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}'
        IID_IFileDialog      = '{42F85136-DB7E-439C-85F1-E4075D135FC8}'
        IID_IShellItem       = '{43826D1E-E718-42EE-BC55-A1E261C37BFE}'

        FOS_PICKFOLDERS     = 0x00000020
        FOS_FORCEFILESYSTEM = 0x00000040
        FOS_PATHMUSTEXIST   = 0x00000800

        def _guid(s):
            arr = (ctypes.c_byte * 16)()
            hr = ole32.CLSIDFromString(s, ctypes.byref(arr))
            print(f"[PICKER] CLSIDFromString({s}) hr={hr:#010x}", flush=True)
            return arr

        clsid = _guid(CLSID_FileOpenDialog)
        iid   = _guid(IID_IFileDialog)

        dialog_ptr = ctypes.c_void_p(None)
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid), None, 1,
            ctypes.byref(iid),
            ctypes.byref(dialog_ptr),
        )
        print(f"[PICKER] CoCreateInstance hr={hr:#010x} ptr={dialog_ptr.value}", flush=True)
        if hr != 0 or not dialog_ptr:
            print("[PICKER] CoCreateInstance FAILED — returning ''", flush=True)
            return ''

        def _vtbl(ptr, index, restype, *argtypes):
            vt    = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))
            fn    = ctypes.cast(vt[0], ctypes.POINTER(ctypes.c_void_p))
            proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
            return proto(fn[index])

        ptr = dialog_ptr.value

        # SetOptions
        set_opts_fn = _vtbl(ptr, 9, ctypes.HRESULT, ctypes.c_uint)
        hr = set_opts_fn(ptr, FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST)
        print(f"[PICKER] SetOptions hr={hr:#010x}", flush=True)

        # SetTitle
        set_title_fn = _vtbl(ptr, 17, ctypes.HRESULT, ctypes.c_wchar_p)
        hr = set_title_fn(ptr, title)
        print(f"[PICKER] SetTitle hr={hr:#010x}", flush=True)

        # Show
        hwnd = _get_foreground_hwnd()
        print(f"[PICKER] Show hwnd={hwnd}", flush=True)
        show_fn = _vtbl(ptr, 3, ctypes.HRESULT, ctypes.wintypes.HWND)
        hr = show_fn(ptr, hwnd)
        print(f"[PICKER] Show hr={hr:#010x}", flush=True)

        if hr != 0:
            print(f"[PICKER] Show cancelled/failed hr={hr:#010x}", flush=True)
            release_fn = _vtbl(ptr, 2, ctypes.c_ulong)
            release_fn(ptr)
            return ''

        # GetResult
        item_ptr = ctypes.c_void_p(None)
        get_result_fn = _vtbl(ptr, 20, ctypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))
        hr = get_result_fn(ptr, ctypes.byref(item_ptr))
        print(f"[PICKER] GetResult hr={hr:#010x} item={item_ptr.value}", flush=True)
        if hr != 0 or not item_ptr:
            release_fn = _vtbl(ptr, 2, ctypes.c_ulong)
            release_fn(ptr)
            return ''

        # IShellItem::GetDisplayName
        SIGDN_FILESYSPATH = 0x80058000
        path_ptr  = ctypes.c_wchar_p(None)
        si_ptr    = item_ptr.value
        get_dn_fn = _vtbl(si_ptr, 5, ctypes.HRESULT,
                          ctypes.c_uint, ctypes.POINTER(ctypes.c_wchar_p))
        hr = get_dn_fn(si_ptr, SIGDN_FILESYSPATH, ctypes.byref(path_ptr))
        print(f"[PICKER] GetDisplayName hr={hr:#010x} path={path_ptr.value!r}", flush=True)

        path = path_ptr.value or '' if hr == 0 else ''
        if path_ptr:
            ole32.CoTaskMemFree(path_ptr)

        si_release = _vtbl(si_ptr, 2, ctypes.c_ulong)
        si_release(si_ptr)
        release_fn = _vtbl(ptr, 2, ctypes.c_ulong)
        release_fn(ptr)

        print(f"[PICKER] returning path={path!r}", flush=True)
        return path

    except Exception as e:
        print(f"[PICKER] EXCEPTION: {e}\n{traceback.format_exc()}", flush=True)
        return ''
    finally:
        ole32.CoUninitialize()


def _win_pick_file(title: str, filetypes, save: bool = False,
                   default_ext: str = '') -> str:
    import ctypes, ctypes.wintypes

    ctypes.windll.ole32.CoInitialize(None)
    try:
        filter_parts = []
        for desc, pattern in (filetypes or [('All files', '*.*')]):
            filter_parts.append(desc + '\0' + pattern)
        filter_str = '\0'.join(filter_parts) + '\0\0'

        OFN_EXPLORER        = 0x00080000
        OFN_FILEMUSTEXIST   = 0x00001000
        OFN_OVERWRITEPROMPT = 0x00000002
        OFN_NOCHANGEDIR     = 0x00000008

        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [
                ('lStructSize',       ctypes.wintypes.DWORD),
                ('hwndOwner',         ctypes.wintypes.HWND),
                ('hInstance',         ctypes.wintypes.HINSTANCE),
                ('lpstrFilter',       ctypes.wintypes.LPCWSTR),
                ('lpstrCustomFilter', ctypes.wintypes.LPWSTR),
                ('nMaxCustFilter',    ctypes.wintypes.DWORD),
                ('nFilterIndex',      ctypes.wintypes.DWORD),
                ('lpstrFile',         ctypes.wintypes.LPWSTR),
                ('nMaxFile',          ctypes.wintypes.DWORD),
                ('lpstrFileTitle',    ctypes.wintypes.LPWSTR),
                ('nMaxFileTitle',     ctypes.wintypes.DWORD),
                ('lpstrInitialDir',   ctypes.wintypes.LPCWSTR),
                ('lpstrTitle',        ctypes.wintypes.LPCWSTR),
                ('Flags',             ctypes.wintypes.DWORD),
                ('nFileOffset',       ctypes.wintypes.WORD),
                ('nFileExtension',    ctypes.wintypes.WORD),
                ('lpstrDefExt',       ctypes.wintypes.LPCWSTR),
                ('lCustData',         ctypes.c_void_p),
                ('lpfnHook',          ctypes.c_void_p),
                ('lpTemplateName',    ctypes.wintypes.LPCWSTR),
                ('pvReserved',        ctypes.c_void_p),
                ('dwReserved',        ctypes.wintypes.DWORD),
                ('FlagsEx',           ctypes.wintypes.DWORD),
            ]

        file_buf = ctypes.create_unicode_buffer(32768)
        file_ptr = ctypes.cast(file_buf, ctypes.wintypes.LPWSTR)

        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner   = _get_foreground_hwnd()
        ofn.lpstrFilter = filter_str
        ofn.lpstrFile   = file_ptr
        ofn.nMaxFile    = len(file_buf)
        ofn.lpstrTitle  = title
        ofn.lpstrDefExt = default_ext.lstrip('.')
        ofn.Flags       = OFN_EXPLORER | OFN_NOCHANGEDIR

        if save:
            ofn.Flags |= OFN_OVERWRITEPROMPT
            ok = ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn))
        else:
            ofn.Flags |= OFN_FILEMUSTEXIST
            ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

        return file_buf.value if ok else ''
    finally:
        ctypes.windll.ole32.CoUninitialize()


# ── Tkinter fallback (non-Windows) ───────────────────────────────────────────

class _TkFallbackDispatcher:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._run, name='TkDialogDispatcher', daemon=True)
        t.start()

    def _run(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            while True:
                try:
                    job = self._queue.get(timeout=1)
                    if job is None: break
                    job['result'].append('')
                    job['done'].set()
                except Exception:
                    pass
            return

        root = tk.Tk()
        root.withdraw()
        while True:
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                root.update_idletasks()
                continue
            if job is None:
                break
            try:
                owner = tk.Toplevel(root)
                owner.geometry('1x1+0+0')
                owner.attributes('-topmost', True)
                owner.lift(); owner.focus_force(); owner.update()
                if job['mode'] == 'file' and job.get('save'):
                    path = filedialog.asksaveasfilename(
                        parent=owner, title=job['title'],
                        defaultextension=job.get('default_ext', ''),
                        filetypes=job.get('filetypes') or [('All', '*.*')])
                elif job['mode'] == 'file':
                    path = filedialog.askopenfilename(
                        parent=owner, title=job['title'],
                        filetypes=job.get('filetypes') or [('All', '*.*')])
                else:
                    path = filedialog.askdirectory(parent=owner, title=job['title'])
                job['result'].append(path or '')
            except Exception:
                job['result'].append('')
            finally:
                try: owner.destroy()
                except Exception: pass
                job['done'].set()

    def pick(self, mode, title, filetypes=None, save=False, default_ext=''):
        result_box = []
        done_event = threading.Event()
        self._queue.put({'mode': mode, 'title': title, 'filetypes': filetypes,
                         'save': save, 'default_ext': default_ext,
                         'result': result_box, 'done': done_event})
        done_event.wait(timeout=120)
        return result_box[0] if result_box else ''


# ── Public dispatcher ─────────────────────────────────────────────────────────

class TkDialogDispatcher:
    def __init__(self):
        self._fallback = None if sys.platform == 'win32' else _TkFallbackDispatcher()

    def pick(self, mode: str, title: str, filetypes=None,
             save: bool = False, default_ext: str = '') -> str:
        if self._fallback:
            return self._fallback.pick(mode, title, filetypes, save, default_ext)
        if mode == 'folder':
            return _win_pick_folder(title)
        else:
            return _win_pick_file(title, filetypes, save=save, default_ext=default_ext)


# ── Flask route registration ──────────────────────────────────────────────────

def register_routes(server, dispatcher: TkDialogDispatcher):

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