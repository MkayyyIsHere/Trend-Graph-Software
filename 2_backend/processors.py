# =============================================================================
# DATA PROCESSING — Gantt/Event
# (analyser data files are read by backend/formats.py)
# =============================================================================

import re
from datetime import datetime, timedelta
from typing import List

import pandas as pd
from backend.models import Task

EVENT_COLUMNS = ('Test Description', 'Test ID', 'Date', 'Start Time', 'End Time', 'Normalized Time')
EVENT_EXTS    = ('.csv', '.txt', '.xlsx', '.xlsm', '.xls')

_DATE_FORMATS = ('%d/%m/%Y', '%d/%m/%y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d', '%Y/%m/%d',
                 '%d %b %Y', '%d-%b-%Y', '%d-%b-%y', '%d %B %Y')


def _canon(name) -> str:
    return re.sub(r'[^a-z]', '', str(name).lower())


_CANON_COLUMNS = {_canon(c): c for c in EVENT_COLUMNS}


def event_plot_window(tasks):
    """Plot window for a schedule: first event start … last event end.
    None if no tasks."""
    if not tasks:
        return None
    return (min(t.start_time for t in tasks).replace(microsecond=0),
            max(t.end_time for t in tasks).replace(microsecond=0))


class EventDataProcessor:
    def __init__(self, logger=None):
        self.logger = logger
        self.tasks: List[Task] = []
        self.error: str = ''             # why load_csv() returned False, for the UI
        self.problems: List[str] = []    # rows skipped / patched, for the UI

    def _log(self, msg: str, level: str = 'INFO'):
        if level in ('WARNING', 'ERROR'):
            self.problems.append(msg)
        if self.logger:
            getattr(self.logger, level.lower())(msg)

    def load_csv(self, file_path: str) -> bool:
        """Load a schedule from CSV or Excel (name kept for existing callers)."""
        try:
            self.tasks, self.error, self.problems = [], '', []
            df, header_row = self._read_table(file_path)
            if df is None:
                self.error = ("No header row with the columns Test Description, Date and "
                              "Start Time was found in the first 20 rows"
                              + (" of any sheet." if file_path.lower().endswith(
                                  ('.xlsx', '.xlsm', '.xls')) else "."))
                self._log(self.error, 'ERROR')
                return False
            self._log(f"Event file loaded: {file_path}")
            self._log(f"Processing {len(df)} rows")
            for idx, row in df.iterrows():
                # row_num = spreadsheet row number, for messages
                self._process_row(row, idx + header_row + 2)
            self._log(f"Successfully processed {len(self.tasks)} valid tasks")
            if not self.tasks:
                self.error = "The header was found but no row had a readable date and times."
            return True
        except PermissionError:
            self.error = "The file is open in another program (e.g. Excel) — close it and try again."
            self._log(self.error, 'ERROR')
            return False
        except Exception as e:
            self.error = f"Could not read the file: {e}"
            self._log(f"Error loading event file: {e}", 'ERROR')
            return False

    def _read_table(self, file_path: str):
        """Return (DataFrame with canonical column names, header row index).

        The header row is found by name (it may sit below a title block), and
        column names are matched loosely ('test id', 'TestID', 'Start time' …).
        Excel: the first sheet that has the schedule columns is used."""
        if file_path.lower().endswith(('.xlsx', '.xlsm', '.xls')):
            sheets = pd.read_excel(file_path, sheet_name=None, header=None, dtype=object)
            raws   = list(sheets.values())
        else:
            raws = [pd.read_csv(file_path, header=None, dtype=str, quotechar='"',
                                engine='python', encoding='utf-8-sig')]

        for raw in raws:
            for r in range(min(len(raw), 20)):
                names = [_CANON_COLUMNS.get(_canon(v), v) for v in raw.iloc[r]]
                if {'Test Description', 'Date', 'Start Time'} <= set(names):
                    df = raw.iloc[r + 1:].reset_index(drop=True)
                    df.columns = names
                    return df.dropna(how='all'), r
        return None, 0

    @staticmethod
    def _cell_str(value) -> str:
        """Excel gives datetime / time objects; render them like CSV text."""
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d') if value.time() == datetime.min.time()                 else value.strftime('%Y-%m-%d %H:%M')
        if hasattr(value, 'strftime'):          # datetime.time
            return value.strftime('%H:%M')
        return '' if value is None else str(value).strip()

    def _parse_date(self, date_str: str):
        date_str = date_str.split(' ')[0] if re.match(r'^\d{4}-\d{2}-\d{2} ', date_str) else date_str
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    def _process_row(self, row, row_num: int):
        try:
            cell                = lambda k: self._cell_str(row.get(k, ''))  # noqa: E731
            description         = cell('Test Description')
            test_id             = cell('Test ID')
            date_str            = cell('Date')
            start_time_str      = cell('Start Time')
            end_time_str        = cell('End Time')
            normalized_time_str = cell('Normalized Time')

            is_normalization = bool(normalized_time_str and normalized_time_str.lower() != 'nan')

            if not description or description.lower() == 'nan':
                self._log(f"Row {row_num}: Missing description, skipping", 'WARNING'); return
            if not test_id or test_id == '-' or test_id.lower() == 'nan':
                test_id = 'UNASSIGNED'
                self._log(f"Row {row_num}: Missing test ID, assigned as 'UNASSIGNED'", 'WARNING')
            if not date_str or date_str.lower() == 'nan':
                self._log(f"Row {row_num}: Missing date, skipping", 'WARNING'); return
            date_obj = self._parse_date(date_str)
            if date_obj is None:
                self._log(f"Row {row_num}: Invalid date format '{date_str}', skipping", 'WARNING'); return

            start_time, end_time = self._parse_start_end(date_obj, start_time_str, end_time_str, row_num)
            if start_time and end_time:
                self.tasks.append(Task(description, test_id, start_time, end_time,
                                       is_normalization=False, row_number=row_num - 1))

            if is_normalization:
                norm_start, norm_end = self._parse_duration_range(date_obj, normalized_time_str, row_num)
                if norm_start and norm_end:
                    self.tasks.append(Task(description, test_id, norm_start, norm_end,
                                           is_normalization=True, row_number=row_num - 1))
        except Exception as e:
            self._log(f"Row {row_num}: Unexpected error - {e}", 'ERROR')

    def _parse_start_end(self, date_obj, start_str, end_str, row_num):
        cross_day_re  = re.compile(r'^\d{1,2}/\d{1,2}\s+')
        time_token_re = re.compile(r'(\d{1,2})\s*:\s*(\d{2})\s*(am|pm)', re.IGNORECASE)

        def strip_prefix(s):
            m = cross_day_re.match(s)
            return (s[m.end():], True) if m else (s, False)

        def extract_times(raw):
            return [(int(h), int(m), ap) for h, m, ap in time_token_re.findall(raw)]

        def parse_side(raw):
            if not raw or raw.lower() == 'nan':
                return None, False
            cleaned, cross = strip_prefix(raw)
            tokens = extract_times(cleaned)
            if tokens:
                h, m, ap = tokens[0]
                dt = self._create_datetime(date_obj, h, m, ap)
            else:
                dt = self._parse_time(cleaned, date_obj, row_num)
            if dt and cross:
                dt += timedelta(days=1)
            return dt, cross

        start_time, _ = parse_side(start_str)
        end_time = None
        if end_str and end_str.lower() != 'nan':
            cleaned, cross = strip_prefix(end_str)
            tokens = extract_times(cleaned)
            if tokens:
                h, m, ap = tokens[-1]
                end_time = self._create_datetime(date_obj, h, m, ap)
            else:
                end_time = self._parse_time(cleaned, date_obj, row_num)
            if end_time and cross:
                end_time += timedelta(days=1)

        if start_time and end_time:
            if end_time < start_time:
                end_time += timedelta(days=1)
            return start_time, end_time
        if end_time:
            return end_time - timedelta(minutes=30), end_time
        if start_time:
            return start_time, start_time + timedelta(minutes=30)
        self._log(f"Row {row_num}: Could not parse start/end times, skipping", 'WARNING')
        return None, None

    def _parse_duration_range(self, date_obj, range_str, row_num):
        try:
            cleaned = re.sub(r'[A-Z]+-\d+:\s*', '', range_str.strip())
            times   = re.findall(r'(\d{1,2})\s*:\s*(\d{2})\s*(am|pm|AM|PM)', cleaned)
            if len(times) >= 2:
                st = self._create_datetime(date_obj, int(times[0][0]), int(times[0][1]), times[0][2])
                et = self._create_datetime(date_obj, int(times[1][0]), int(times[1][1]), times[1][2])
                if et < st:
                    et += timedelta(days=1)
                return st, et
            if len(times) == 1:
                et = self._create_datetime(date_obj, int(times[0][0]), int(times[0][1]), times[0][2])
                return et - timedelta(minutes=30), et
        except Exception as e:
            self._log(f"Row {row_num}: Error parsing range '{range_str}': {e}", 'WARNING')
        return None, None

    def _parse_time(self, time_str, date_obj, row_num):
        for fmt in ('%I:%M%p', '%H:%M', '%I:%M %p', '%H:%M:%S', '%I:%M:%S %p', '%I.%M%p', '%H.%M'):
            try:
                return datetime.combine(date_obj.date(),
                                        datetime.strptime(time_str.strip(), fmt).time())
            except ValueError:
                continue
        self._log(f"Row {row_num}: Could not parse time '{time_str}'", 'WARNING')
        return None

    def _create_datetime(self, date_obj, hour, minute, ampm):
        ampm = ampm.lower()
        if ampm == 'pm' and hour != 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
        return datetime.combine(date_obj.date(), datetime.min.time()).replace(hour=hour, minute=minute)

    def get_tasks(self) -> List[Task]:
        return self.tasks

    def get_summary(self) -> dict:
        if not self.tasks:
            return {'total_tasks': 0, 'test_ids': [], 'date_range': (None, None)}
        test_ids = list(dict.fromkeys(t.test_id for t in self.tasks))
        return {
            'total_tasks': len(self.tasks),
            'test_ids':    test_ids,
            'date_range':  (min(t.start_time for t in self.tasks),
                            max(t.end_time   for t in self.tasks)),
        }
