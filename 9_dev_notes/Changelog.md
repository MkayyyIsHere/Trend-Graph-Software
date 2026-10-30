# Changelog

All notable changes to Trend Graph Software are listed here.
Format: version — date — what changed

---

## [1.0.0] — 2026-03-30
- Initial release

## [1.0.1] — 2026-04-02
- Fix file picker and folder picker

## [1.0.2] — 2026-04-0
- Fix Config manager's Aesthetics
- Update Settings
- Update on asethetics guide
- Updated new config file
- Fix Config Editor (min y, max y)

## [1.0.3] - 2026-05-11
- Updated on PF plottings

## [1.0.4] - 2026-05-26
- Final Update on PF plots

## [1.0.5] - 2026-05-28
- Update on Y-axis appearance

## [1.1.0] - unreleased
- New 🚀 Quick Run tab (default): Events → Data → Generate & Export in one page
- Plot time window is derived from the event schedule (±30 min); no more editing x_min/x_max
- Per-chart Y min / Y max (or Auto) editable on the Quick Run tab, remembered between runs
- Default charts, colours and PPT template are bundled in the .exe — no config folder needed
- Folders, event file and chart choices are remembered in %APPDATA%\TrendGraph\settings.json
- After a run: Open folder, Build PowerPoint (slides in chart order) and Download ZIP
- Existing tabs kept as advanced tools
- Test schedule can be CSV or Excel (.xlsx); header row found automatically, flexible column names,
  date formats (d/m/Y, Y-m-d, 24 Jan 2026 …) and 24-hour or am/pm times
- Advanced batch also derives the plot window from the schedule when a chart has no x_min/x_max
- X-axis tick spacing adapts to the window length (15 min … 6 h)
- Warning when a data file has no samples inside the plot window
- Hioki support (PQ3198-style CSV: Date+Time columns, BOM, 1E+00 numbers, OVER/----- as gaps)
  alongside Fluke; brand shown per file in the Quick Run tab
- System wiring choice (3P4W with N / 3P3W without N): voltage & THD show L-N or L-L accordingly;
  Hioki U1–U3 vs U12/U23/U31 are always labelled correctly
- Charts now pick columns by measurement ("metric") instead of fixed column names
- Neutral current line added to the Current chart when the export has one
- Power / PF charts are skipped with a note for exports that only have totals
- FIX: Current chart was plotting the same (last) column three times on Fluke exports
- FIX: Active Power chart plotted a current column on Fluke exports without PowerPfund;
  it now uses PowerP (total active power) for every Fluke export
- Data files are parsed once per run and vectorised (~0.1–0.5 s per file instead of ~10 s × 18)
- Display units: power W/kW/MW, voltage V/kV, current A/kA, frequency Hz/kHz — Unit column per chart
  on the Quick Run tab (Auto or fixed). Auto picks the unit from the Y limits, or from the largest
  reading across all files when Auto Y is on, so every slide of a chart uses the same unit
- Y-axis label and hover values carry the unit; Y limits are stored in W/V/A and shown in the chosen unit
- FIX: Active Power axis said "kW" while plotting W
- Faster charts: one trace per series from NumPy arrays (cropped to the plot window), min/max
  decimation to ~2 points per pixel for image export (no visible change), Gantt shapes and labels
  set in one go — 30 charts in ~18 s (was ~100 s; ~225 s before 1.1.0)
- Recording gaps are detected relative to the logging interval (> 3× interval, min 2 s), so exports
  logged every 10 s / 1 min draw as lines instead of separate points
- Auto Y fits the data inside the plot window rather than the whole file
