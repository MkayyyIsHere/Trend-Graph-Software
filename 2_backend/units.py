# =============================================================================
# DISPLAY UNITS — scale chart values to W/kW/MW, V/kV, A/kA, …
#
# Analyser exports carry plain SI values (W, V, A, Hz). Everything stored —
# chart JSON y_min/y_max, wizard Y limits — stays in those base units; only
# the plotted values, Y limits and Y-axis label are converted at draw time.
#
# Unit choice per chart: 'auto' or a concrete unit ('kW', 'V', …).
#   auto + fixed Y limits → unit picked from the limits
#   auto + Auto Y         → unit picked from the data peak (whole batch)
# Dimensionless charts (power factor, THD %) are never scaled.
# =============================================================================

import re
from typing import List, Optional

from backend.models import DataPoint

AUTO = 'auto'

# Base unit per chart metric (None = dimensionless, not scaled)
METRIC_UNITS = {
    'voltage':      'V',
    'current':      'A',
    'active_power': 'W',
    'frequency':    'Hz',
    'thd_voltage':  None,
    'power_factor': None,
}

_PREFIXES = (('', 1.0), ('k', 1e3), ('M', 1e6))

# Keep displayed numbers below this before stepping up a prefix, so 1500 A
# stays "1500 A" while 137 500 W becomes "137.5 kW".
_STEP_UP = 10_000


def base_unit(cfg_dict: dict) -> Optional[str]:
    """Base SI unit of a chart config: explicit "base_unit" key, else from its metric."""
    if cfg_dict.get('base_unit'):
        return cfg_dict['base_unit']
    return METRIC_UNITS.get(cfg_dict.get('metric'))


def unit_options(base: Optional[str]) -> List[str]:
    """['W', 'kW', 'MW'] for a base unit; [] when the chart is dimensionless."""
    return [p + base for p, _ in _PREFIXES] if base else []


def factor(unit: str, base: str) -> float:
    """Multiplier from *unit* to *base* (kW → W = 1000)."""
    for p, f in _PREFIXES:
        if unit == p + base:
            return f
    return 1.0


def pick_unit(base: str, peak: Optional[float]) -> str:
    """Largest prefix that keeps |peak| displayed below 10 000."""
    for p, f in _PREFIXES:
        if abs(peak or 0) / f < _STEP_UP:
            return p + base
    return _PREFIXES[-1][0] + base


def resolve_unit(choice: Optional[str], base: Optional[str],
                 y_min=None, y_max=None, data_peak=None) -> Optional[str]:
    """Concrete display unit for a chart, or None when it is not scalable."""
    if not base:
        return None
    if choice and choice != AUTO and choice in unit_options(base):
        return choice
    if y_min is not None and y_max is not None:
        return pick_unit(base, max(abs(float(y_min)), abs(float(y_max))))
    return pick_unit(base, data_peak)


def label_with_unit(label: str, unit: str) -> str:
    """'Active Power (kW)' + 'MW' → 'Active Power (MW)'; appends when no unit is shown."""
    label = (label or '').strip()
    stripped = re.sub(r'\s*\([^()]*\)\s*$', '', label)
    return f"{stripped or 'Value'} ({unit})"


def apply_display_unit(cfg, all_dp: List[List[DataPoint]], choice: Optional[str] = AUTO,
                       data_peak: Optional[float] = None) -> Optional[str]:
    """Scale data points, Y limits and Y label of *cfg* in place. Returns the unit used."""
    base = base_unit(cfg.config)
    axis = cfg.config.setdefault('axis', {})
    if data_peak is None:
        data_peak = max((abs(dp.value) for pts in all_dp for dp in pts), default=None)
    unit = resolve_unit(choice, base, axis.get('y_min'), axis.get('y_max'), data_peak)
    if unit is None:
        return None
    f = factor(unit, base)
    if f != 1.0:
        for pts in all_dp:
            for dp in pts:
                dp.value /= f
        for k in ('y_min', 'y_max'):
            if axis.get(k) is not None:
                axis[k] = float(axis[k]) / f
    axis['y_label'] = label_with_unit(axis.get('y_label', ''), unit)
    return unit
