# =============================================================================
# DATA MODELS  (unchanged)
# =============================================================================

from datetime import datetime

class DataPoint:
    def __init__(self, timestamp: datetime, value: float):
        self.timestamp = timestamp
        self.value     = value


class Task:
    def __init__(self, description: str, test_id: str, start_time: datetime,
                 end_time: datetime, is_normalization: bool = False, row_number: int = 0):
        self.description      = description
        self.test_id          = test_id
        self.start_time       = start_time
        self.end_time         = end_time
        self.is_normalization = is_normalization
        self.row_number       = row_number

    @property
    def display_id(self) -> str:
        return f"{self.test_id} (N)" if self.is_normalization else self.test_id

    @property
    def legend_no(self) -> str:
        return f"{self.row_number}(N)" if self.is_normalization else str(self.row_number)