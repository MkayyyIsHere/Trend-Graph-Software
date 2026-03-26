"""1_app/state.py — Thread-safe shared state for the Dash application."""
import os
import threading
from typing import List, Optional

from utils.constants import DEFAULT_GANTT_CONFIG_PATH
from utils.logger import GUILogger
from backend.models import DataPoint, Task
from backend.config import ConfigManager, GanttConfigManager



class AppState:
    """Holds all mutable runtime state shared between callbacks and background threads."""

    def __init__(self):
        # Log buffers (appended by threads, read by polling callbacks)
        self.log_lines:     List[str] = []
        self.batch_log:     List[str] = []
        self.ppt_log_lines: List[str] = []

        # Batch state
        self.batch_running    = False
        self.batch_result:    Optional[dict] = None
        self.batch_stop_event = threading.Event()

        # PPT state
        self.ppt_running = False
        self.ppt_result:  Optional[dict] = None

        # Backend config objects (reloaded per file-path change)
        _default = DEFAULT_GANTT_CONFIG_PATH if os.path.exists(DEFAULT_GANTT_CONFIG_PATH) else None
        self.config       = ConfigManager(_default)
        self.gantt_config = GanttConfigManager(_default)
        self.logger       = GUILogger(callback=self.log_lines.append)

        # Last generated chart artifacts (kept in memory, no temp file)
        self.last_all_data_points: Optional[List[List[DataPoint]]] = None
        self.last_tasks:            Optional[List[Task]]            = None
        self.last_png_bytes:        Optional[bytes]                 = None
        self.last_pptx_path:        Optional[str]                   = None