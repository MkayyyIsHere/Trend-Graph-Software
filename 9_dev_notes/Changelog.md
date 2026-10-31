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

## [1.1.0] - 2026-10-30
- New 🚀 Quick Run tab (default): Events → Data → Generate & Export in one page
- Plot time window is derived from the event schedule (first start → last end); no more editing x_min/x_max
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
- PowerPoint template picker on the Quick Run tab (remembered, falls back to the built-in one)
- Clearer errors: schedule problems name the missing header / unreadable rows (listed per row);
  failed charts list their reasons in the results panel; a run that cannot start (schedule
  unreadable, no Edge/Chrome for image export) says why instead of hanging
- FIX: a chart that could not be saved (e.g. PNG open in a viewer) froze the whole run; the image
  renderer is now app-managed (serialised, per-chart timeout, auto-restart) and a locked file
  only fails that one chart with a clear message
- Exported images no longer show faint duplicate series names behind the legend
- Image export no longer fetches MathJax from the internet (works offline / behind a proxy)
- build.py works from any folder, bundles kaleido/choreographer files; .exe needs nothing alongside it

## [1.2.0] - 2026-10-31
- Quick Run laid out as a bento: Events and Data on the left, Generate & Export on the right;
  fits a 100%-zoom browser window without page scrolling
- New 🔍 Results tab replaces "Single Chart & Batch" and "Live Preview": charts appear while the run
  is drawing; ◀ ▶ / arrow keys, thumbnail strip, filter by data file or chart; "Interactive" redraws
  the current chart as a zoomable chart with the same window, Y limits and units; can also open any
  folder of PNGs for viewing; run log kept at the bottom
- 📑 PowerPoint tab simplified: slides default to the last run, tick/untick and ▲▼ to choose the
  order, template remembered from Quick Run, file name prefilled; DPI/resize/output folder under
  "More options"
- ⚙️ Config Manager is one list (Global style, Event colours, then each chart in run order) with a
  summary per row and the editor beside it; ▲▼ reorders and saves straight away; "Copy built-in
  charts to a folder…" to start customising; the config folder is remembered
- Event (Gantt) colours saved per PC in %APPDATA%\TrendGraph\gantt.json
- Saving a chart in Config Manager keeps its metric and other fields not on the form
- Settings window removed (resolution/DPI live in Global style); parallel workers fixed at 2
  (measured: more workers gave no speed-up because image rendering is serialised)
- Config Manager shows "● Unsaved changes" (Save turns orange) after an edit; switching entry or
  generating charts with unsaved edits asks first, so edits aren't silently left out of a run
- Optional event styling in gantt.json (gantt section): label_color, label_bg, label_border,
  legend_id_color, edge_dash and normalization_color (e.g. "dash"); all default to the previous look
- Event colours are re-read at the start of each run (and in Config Manager), so a changed
  gantt.json applies without restarting the app
- A config folder can hold its own gantt.json (event colours); it wins over this PC's copy and the
  built-in one, and Config Manager saves Event colours there when a folder is chosen
- New default chart look: vivid phase colours shared by every chart (A #F50057, B #2962FF,
  C #FF8F00, N #263238; solid, 2 px), faint grid, and a muted slate event layer (dashed start/end
  lines, soft-tag IDs) so the data stands out; titles shortened to "<Measurement> Trend"
