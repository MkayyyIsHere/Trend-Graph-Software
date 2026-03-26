# =============================================================================
# LOGGER  (adapted: callback is a thread-safe list append)
# =============================================================================
import logging
from datetime import datetime


class GUILogger:
    _LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}

    def __init__(self, callback=None):
        self.callback = callback
        self._logger  = logging.getLogger('CompositeDataPlotter')
        self._logger.setLevel(logging.DEBUG)
        if not self._logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                             datefmt='%Y-%m-%d %H:%M:%S'))
            self._logger.addHandler(h)

    def log(self, level: str, message: str):
        getattr(self._logger, level.lower())(message)
        if self.callback:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.callback(f"[{ts}] {level}: {message}")

    def debug(self,    msg): self.log('DEBUG',    msg)
    def info(self,     msg): self.log('INFO',     msg)
    def warning(self,  msg): self.log('WARNING',  msg)
    def error(self,    msg): self.log('ERROR',    msg)
    def critical(self, msg): self.log('CRITICAL', msg)