"""1_app/state.py — Thread-safe shared state for the Dash application."""
import os
import threading
from collections import deque
from typing import List, Optional

from utils.constants import (DEFAULT_GANTT_CONFIG_PATH, DEFAULT_AESTHETICS_PATH, GANTT_FILENAME,
                             user_gantt_path)
from utils.logger import GUILogger
from backend.config import ConfigManager, GanttConfigManager



class AppState:
    """Holds all mutable runtime state shared between callbacks and background threads."""

    def __init__(self):
        # Log buffers (appended by threads, read by polling callbacks).
        # log_lines (backend logger) is no longer shown, so keep only the tail.
        self.log_lines = deque(maxlen=2000)
        self.batch_log:     List[str] = []
        self.ppt_log_lines: List[str] = []

        # Batch state
        self.batch_running    = False
        self.batch_result:    Optional[dict] = None
        self.batch_stop_event = threading.Event()

        # Results viewer: one dict per image {path, data_file, chart, cfg_path, order},
        # appended by the batch thread as each chart is saved. results_ctx is the
        # run context (see batch_worker.load_run_config); None = images from a
        # folder, which can be viewed but not redrawn interactively.
        self.results:     List[dict]     = []
        self.results_ctx: Optional[dict] = None
        self.results_lock = threading.Lock()

        # PPT state
        self.ppt_running = False
        self.ppt_result:  Optional[dict] = None

        # Backend config objects (reloaded per file-path change)
        self.logger       = GUILogger(callback=self.log_lines.append)
        self.config       = ConfigManager(
            config_path     = None,
            aesthetics_path = DEFAULT_AESTHETICS_PATH,
            logger          = self.logger,
        )
        self.gantt_config = GanttConfigManager(None)
        self._gantt_stamp = None
        self.refresh_gantt()

        self.last_pptx_path: Optional[str] = None

    def refresh_gantt(self, folder: str = None):
        """Event colours: <config folder>/gantt.json wins, then this PC's copy
        (%APPDATA%), then the bundled one. Re-read whenever the chosen file
        appears, changes or goes, so an edit on disk applies to the next run
        without restarting the app."""
        here = os.path.join(folder, GANTT_FILENAME) if folder else None
        path = next((p for p in (here, user_gantt_path(), DEFAULT_GANTT_CONFIG_PATH)
                     if p and os.path.exists(p)), None)
        stamp = (path, os.path.getmtime(path) if path else None)
        if stamp != self._gantt_stamp:
            if path:
                self.gantt_config.reload(path)
            self._gantt_stamp = stamp
        return self.gantt_config
