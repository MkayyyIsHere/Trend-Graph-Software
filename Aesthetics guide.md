# Trend Graph Software — Aesthetics Configuration Guide

All visual settings are controlled through the **Aesthetics tab** in the Config Manager.
Changes take effect immediately after clicking **Save aesthetics.json** — no restart required.

---

## How the Layout Works

The figure is divided into two zones:

- **Plot area** — where the data lines, Gantt bars, and axes are drawn
- **Legend column** — where the series list and event descriptions appear

Both zones are defined as fractions of the full figure width/height (0.0 to 1.0).
The key rule: `legend_x` should always be slightly above `right` (e.g. `right: 0.75` → `legend_x: 0.76`).

---

## Layout Parameters

These control the size and position of the plot area and legend column.

### Plot Area Edges

| Parameter | Description | Typical Value |
|---|---|---|
| `Left` | Left edge of the plot area as a fraction of figure width | `0.03` – `0.10` |
| `Right` | Right edge of the plot area. Also defines where the legend column begins | `0.70` – `0.80` |
| `Top` | Top edge of the plot area as a fraction of figure height | `0.90` – `0.95` |
| `Bottom` | Bottom edge of the plot area as a fraction of figure height | `0.05` – `0.10` |

**Example:** `right: 0.75` means the plot occupies 75% of the figure width, leaving 25% for the legend.

### Legend Position

| Parameter | Description | Typical Value |
|---|---|---|
| `Legend X` | Horizontal start of the legend annotation in paper-space. Keep this just above `Right` | `right + 0.01` |
| `Legend Y` | Vertical anchor of the legend annotation. 1.0 = top of figure | `0.80` – `1.0` |

---

## Legend Content Parameters

These control the spacing and text layout inside the legend column.

| Parameter | Description | Typical Value |
|---|---|---|
| `Wrap Width (chars)` | Number of characters before a description line wraps to the next line | `25` – `40` |
| `Pad Top` | Gap (in slot units) between the top of the legend and the first series entry | `0.3` – `0.8` |
| `Sep Above` | Space above the divider line that separates series from event entries | `0.3` – `0.6` |
| `Sep Below` | Space below the divider line before the first event entry | `0.3` – `0.6` |
| `Gap Slots` | Vertical spacing between each event entry | `0.3` – `1.0` |

---

## Font Parameters

| Parameter | Description |
|---|---|
| `Family` | Font family for all text (e.g. `sans-serif`, `Arial`, `Calibri`) |
| `Title Size` | Font size for the chart title |
| `Axis Label Size` | Font size for the X and Y axis labels |
| `Tick Size` | Font size for axis tick labels |
| `Legend Size` | Font size for text inside the legend column |
| `Scale ×` | Global multiplier applied to all font sizes. `1.0` = no scaling |

---

## Chart / Export Parameters

| Parameter | Description |
|---|---|
| `Background Colour` | Background colour of the exported image (default `#ffffff`) |
| `Width (px)` | Export image width in pixels |
| `Height (px)` | Export image height in pixels |
| `DPI` | Dots per inch for the export. Higher = sharper but larger file |
| `LW Scale ×` | Global multiplier for all line widths |

---

## Grid Parameters

| Parameter | Description |
|---|---|
| `Visible` | Show or hide grid lines |
| `Axis` | Which axes to draw grid on: `both`, `x`, or `y` |
| `Line Style` | Grid line style: `-` (solid), `--` (dashed), `-.` (dash-dot), `:` (dotted) |
| `Alpha` | Grid line opacity (0.0 = invisible, 1.0 = fully opaque) |
| `Width` | Grid line thickness in points |
| `Colour` | Grid line colour as a hex value |

---

## Quick Reference: Common Tasks

**Move the legend further right / give it more space**
→ Decrease `Right` (e.g. `0.75` → `0.68`) and set `Legend X` to `Right + 0.01`

**Legend text is getting cut off**
→ Decrease `Right` to give the legend column more horizontal space

**Event descriptions wrapping too early or too late**
→ Adjust `Wrap Width (chars)`

**Too much / too little space between event entries**
→ Adjust `Gap Slots`

**Plot area too tall / too short**
→ Adjust `Top` and `Bottom`

**All text too small on export**
→ Increase individual font sizes, or increase `Scale ×`

---

## What NOT to Change Here

The following are controlled per-chart in the individual chart JSON files (e.g. `1_config_composite_Voltage.json`), not in aesthetics:

- Series colours, line styles, and names
- Chart title
- X and Y axis labels
- Y axis min/max limits
- X axis time range (`x_min`, `x_max`)