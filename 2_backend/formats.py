# =============================================================================
# ANALYSER EXPORT FORMATS — Fluke / Hioki readers and chart → column mapping
#
# load_table(path)        Parse an export once (vectorised, cached): timestamps
#                          + raw columns. Handles Fluke "Start(...)" exports and
#                          Hioki "Date,Time" exports (UTF-8 BOM, 1E+00 numbers,
#                          'OVER' / '-----' invalid markers → gaps).
# load_chart_data(...)     Fill a chart's series from a table:
#                            • chart JSON with "metric" → columns picked from
#                              METRIC_SETS for the wiring system (3P4W / 3P3W)
#                            • legacy chart JSON → per-series value_column /
#                              value_column_keywords (no silent fallback)
# metric_peak(...)         Largest |value| of a chart metric in a file (picks
#                          the display unit for a batch, see units.py)
#
# WHERE TO CHANGE THINGS
# └── a new export naming → add the column name to the candidate lists below
# =============================================================================

import os
import re
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.models import DataPoint

SYSTEMS = ('3P4W', '3P3W')


class ChartSkipped(Exception):
    """The file cannot supply this chart (e.g. no per-phase power) — not an error."""


class DataFileError(Exception):
    """The file could not be read, or a required column is missing."""


# ── Chart metric → column candidates ─────────────────────────────────────────
# Each slot: (label, [candidate column names, case-insensitive]).
# A set is usable when all of its required slots resolve; 'optional' slots
# (neutral) are added only when present with non-zero readings.

_LN_VOLTAGE = [('Vrms AN', ['Vrms_AN_avg', 'U1_rms_AVG']),
               ('Vrms BN', ['Vrms_BN_avg', 'U2_rms_AVG']),
               ('Vrms CN', ['Vrms_CN_avg', 'U3_rms_AVG'])]
_LL_VOLTAGE = [('Vrms AB', ['Vrms_AB_avg', 'U12_rms_AVG']),
               ('Vrms BC', ['Vrms_BC_avg', 'U23_rms_AVG']),
               ('Vrms CA', ['Vrms_CA_avg', 'U31_rms_AVG'])]
_LN_THD     = [('THDv AN', ['Vthd_AN_avg', 'U1_thd-f_AVG']),
               ('THDv BN', ['Vthd_BN_avg', 'U2_thd-f_AVG']),
               ('THDv CN', ['Vthd_CN_avg', 'U3_thd-f_AVG'])]
_LL_THD     = [('THDv AB', ['Vthd_AB_avg', 'U12_thd-f_AVG']),
               ('THDv BC', ['Vthd_BC_avg', 'U23_thd-f_AVG']),
               ('THDv CA', ['Vthd_CA_avg', 'U31_thd-f_AVG'])]
_CURRENT    = [('Irms A', ['Irms_A_avg', 'I1_rms_AVG']),
               ('Irms B', ['Irms_B_avg', 'I2_rms_AVG']),
               ('Irms C', ['Irms_C_avg', 'I3_rms_AVG'])]
_NEUTRAL_I  = [('Irms N', ['Irms_N_avg', 'I4_rms_AVG'])]
_POWER      = [('P Avg A', ['PowerP_A_avg', 'P1_AVG']),
               ('P Avg B', ['PowerP_B_avg', 'P2_AVG']),
               ('P Avg C', ['PowerP_C_avg', 'P3_AVG'])]
_PF         = [('PF Avg A', ['PfFwdRev_A_avg', 'PF1_AVG']),
               ('PF Avg B', ['PfFwdRev_B_avg', 'PF2_AVG']),
               ('PF Avg C', ['PfFwdRev_C_avg', 'PF3_AVG'])]
_FREQUENCY  = [('Frequency', ['Frequency_avg', 'Freq_AVG'])]

# metric → system → ordered alternatives (first usable wins), + optional slots.
# The system only sets the preference: Fluke exports carry both L-N and L-L
# columns, while Hioki names say which they are (U1 = L-N, U12 = L-L), so a
# Hioki file always gets the set it actually has, correctly labelled.
METRIC_SETS: Dict[str, dict] = {
    'voltage':      {'3P4W': [_LN_VOLTAGE, _LL_VOLTAGE], '3P3W': [_LL_VOLTAGE, _LN_VOLTAGE]},
    'thd_voltage':  {'3P4W': [_LN_THD, _LL_THD],         '3P3W': [_LL_THD, _LN_THD]},
    'current':      {'*': [_CURRENT], 'optional': _NEUTRAL_I},
    'frequency':    {'*': [_FREQUENCY]},
    'active_power': {'*': [_POWER],
                     'skip': "the export has no per-phase active power"},
    'power_factor': {'*': [_PF],
                     'skip': "the export has no per-phase power factor"},
}


# ── Reading ──────────────────────────────────────────────────────────────────

_TS_FORMATS = ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S.%f',
               '%d/%m/%Y %H:%M:%S', '%Y/%m/%d %H:%M:%S.%f', '%Y/%m/%d %H:%M:%S',
               '%m/%d/%Y %H:%M:%S', '%d/%m/%Y %I:%M:%S %p', '%Y-%m-%d %I:%M:%S %p')


class Table:
    """One parsed export: python datetimes + raw DataFrame (numeric on demand)."""

    def __init__(self, path: str, brand: str, timestamps: np.ndarray, df: pd.DataFrame):
        self.path       = path
        self.brand      = brand
        self.timestamps = timestamps          # object array of datetime
        self.df         = df
        self._lookup    = {c.strip().lower(): c for c in df.columns}
        self._numeric: Dict[str, np.ndarray] = {}
        self._lock      = threading.Lock()

    @property
    def columns(self) -> List[str]:
        return list(self.df.columns)

    def find(self, name: str) -> Optional[str]:
        return self._lookup.get(name.strip().lower())

    def values(self, column: str) -> np.ndarray:
        with self._lock:
            if column not in self._numeric:
                col = self.df[column]
                if not pd.api.types.is_numeric_dtype(col):     # 'OVER', '-----' → NaN
                    col = pd.to_numeric(col.astype(str).str.strip(), errors='coerce')
                self._numeric[column] = col.to_numpy(dtype=float)
            return self._numeric[column]

    def data_points(self, column: str) -> List[DataPoint]:
        vals = self.values(column)
        keep = ~np.isnan(vals)
        return [DataPoint(t, v) for t, v in zip(self.timestamps[keep], vals[keep].tolist())]


def detect_brand(columns) -> str:
    cols = {c.strip().lower() for c in columns}
    if {'date', 'time'} <= cols and any(re.match(r'^[ui]\d+_rms_avg$', c) for c in cols):
        return 'Hioki'
    if any(c.startswith('start(') for c in cols) or 'vrms_an_avg' in cols or 'vrms_ab_avg' in cols:
        return 'Fluke'
    return 'Unknown'


def sniff_brand(path: str) -> str:
    """Cheap brand check from the header line only (for UI listings)."""
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            header = f.readline()
        sep = max((',', '\t', ';'), key=header.count)
        return detect_brand(header.strip().split(sep))
    except OSError:
        return 'Unknown'


def _parse_timestamps(text: pd.Series) -> pd.Series:
    """Pick the format that parses the most rows (ties: first in _TS_FORMATS,
    i.e. day-first); fall back to pandas' mixed parser."""
    text   = text.astype(str).str.strip()
    sample = text.dropna().head(500)
    best, best_ok = None, 0
    for fmt in _TS_FORMATS:
        ok = pd.to_datetime(sample, format=fmt, errors='coerce').notna().sum()
        if ok > best_ok:
            best, best_ok = fmt, ok
    if best and best_ok >= 0.9 * len(sample):
        return pd.to_datetime(text, format=best, errors='coerce')
    return pd.to_datetime(text, format='mixed', dayfirst=True, errors='coerce')


def _read(path: str) -> Table:
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        header = f.readline()
    sep = max((',', '\t', ';'), key=header.count)
    try:
        df = pd.read_csv(path, sep=sep, encoding='utf-8-sig', low_memory=False)
    except Exception as e:
        raise DataFileError(f"cannot read file: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    brand = detect_brand(df.columns)
    lower = {c.lower(): c for c in df.columns}

    if 'date' in lower and 'time' in lower:
        ts = _parse_timestamps(df[lower['date']].astype(str) + ' ' + df[lower['time']].astype(str))
    else:
        ts_col = next((c for c in df.columns if c.lower().startswith('start')), None) or \
                 next((c for c in df.columns if c.lower() in ('timestamp', 'datetime', 'date/time', 'time')), None) or \
                 df.columns[0]
        ts = _parse_timestamps(df[ts_col])

    keep = ts.notna().to_numpy()
    if not keep.any():
        raise DataFileError("no readable timestamps")
    df = df.loc[keep].reset_index(drop=True)
    stamps = np.array(ts[keep].dt.to_pydatetime(), dtype=object)
    return Table(path, brand, stamps, df)


_CACHE: "OrderedDict[tuple, Table]" = OrderedDict()
_CACHE_SIZE  = 6
_CACHE_LOCK  = threading.Lock()
_PATH_LOCKS: Dict[str, threading.Lock] = {}


def load_table(path: str) -> Table:
    """Parse *path* once; later calls (other charts, other threads) reuse it."""
    st  = os.stat(path)
    key = (os.path.abspath(path), st.st_mtime, st.st_size)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        plock = _PATH_LOCKS.setdefault(key[0], threading.Lock())
    with plock:                                   # one parse per file, even across workers
        with _CACHE_LOCK:
            if key in _CACHE:
                return _CACHE[key]
        table = _read(path)
        with _CACHE_LOCK:
            _CACHE[key] = table
            while len(_CACHE) > _CACHE_SIZE:
                _CACHE.popitem(last=False)
        return table


# ── Column resolution ────────────────────────────────────────────────────────

def _resolve_set(table: Table, slots) -> Optional[List[Tuple[str, str]]]:
    out = []
    for label, candidates in slots:
        col = next((table.find(c) for c in candidates if table.find(c)), None)
        if col is None:
            return None
        out.append((label, col))
    return out


def resolve_metric(table: Table, metric: str, system: str) -> List[Tuple[str, str]]:
    """[(label, column)] for a chart metric, or raise ChartSkipped / DataFileError."""
    spec = METRIC_SETS.get(metric)
    if spec is None:
        raise DataFileError(f"unknown chart metric '{metric}'")
    for slots in spec.get(system) or spec.get('*') or []:
        found = _resolve_set(table, slots)
        if found:
            for label, candidates in spec.get('optional', []):
                col = next((table.find(c) for c in candidates if table.find(c)), None)
                if col is not None and np.nanmax(np.abs(table.values(col)), initial=0) > 0:
                    found.append((label, col))
            return found
    if 'skip' in spec:
        raise ChartSkipped(spec['skip'])
    raise DataFileError(f"no columns for '{metric}' in this {table.brand} export")


def _resolve_legacy(table: Table, sc: dict) -> str:
    """Old-style series config: exact value_column, then keyword substring."""
    vc = sc.get('value_column')
    if vc and table.find(vc):
        return table.find(vc)
    for kw in sc.get('value_column_keywords') or []:
        col = next((c for c in table.columns if kw.lower() in c.lower()), None)
        if col:
            return col
    raise DataFileError(f"column for series '{sc.get('name', '?')}' not found "
                        f"(looked for {vc or sc.get('value_column_keywords')})")


def load_chart_data(cfg, data_path: str, system: str = '3P4W') -> List[List[DataPoint]]:
    """Load the series for one chart config from one data file.

    For metric-based charts the config's series list is replaced by one entry
    per resolved column (style taken from the matching slot), so the legend
    shows what was actually plotted."""
    table  = load_table(data_path)
    metric = cfg.config.get('metric')
    styles = cfg.get_all_series_configs()
    if metric:
        resolved = resolve_metric(table, metric, system)
        series = []
        for i, (label, col) in enumerate(resolved):
            style = dict(styles[i]) if i < len(styles) else {'line_color': '#7f7f7f'}
            style.update(name=label, value_column=col)
            series.append(style)
        cfg.config['series'] = series
        cols = [col for _, col in resolved]
    else:
        cols = [_resolve_legacy(table, sc) for sc in styles]

    all_dp = [table.data_points(c) for c in cols]
    if not any(all_dp):
        raise DataFileError("no valid readings in the selected columns")
    return all_dp


def metric_peak(data_path: str, metric: str, system: str = '3P4W', window=None) -> Optional[float]:
    """Largest |value| a metric chart would plot from one file (inside *window*
    (start, end) when given), or None when the file cannot supply it."""
    try:
        table = load_table(data_path)
        cols  = [col for _, col in resolve_metric(table, metric, system)]
    except (ChartSkipped, DataFileError, OSError, ValueError):
        return None
    mask = None
    if window:
        mask = (table.timestamps >= window[0]) & (table.timestamps <= window[1])
    peaks = []
    for c in cols:
        v = np.abs(table.values(c) if mask is None else table.values(c)[mask])
        if v.size and not np.all(np.isnan(v)):
            peaks.append(float(np.nanmax(v)))
    return max(peaks, default=None)
