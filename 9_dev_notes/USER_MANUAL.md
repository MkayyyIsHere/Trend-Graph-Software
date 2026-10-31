# Trend Graph Software (Elec) — User Manual

> **Version:** 1.2.0
> **Last Updated:** 2026-10-31

---

## Table of Contents

- [Quick Run (recommended)](#quick-run-recommended)
1. [Overview](#1-overview)
2. [Getting Started](#2-getting-started)
   - 2.1 [What You Need](#21-what-you-need)
   - 2.2 [Downloading from SharePoint](#22-downloading-from-sharepoint)
   - 2.3 [Setting Up Your Folders](#23-setting-up-your-folders)
   - 2.4 [Launching the App](#24-launching-the-app)
3. [Config Folder Setup](#3-config-folder-setup)
   - 3.1 [What Is the Config Folder?](#31-what-is-the-config-folder)
   - 3.2 [Folder Structure](#32-folder-structure)
   - 3.3 [Pointing the App to Your Config Folder](#33-pointing-the-app-to-your-config-folder)
4. [Viewing Results](#4-viewing-results)
   - 4.1 [The Results Tab](#41-the-results-tab)
5. [Chart Order](#5-chart-order)
6. [Event Colours (Gantt bars)](#6-event-colours-gantt-bars)
7. [PowerPoint Export](#7-powerpoint-export)
   - 7.1 [Straight after a run](#71-straight-after-a-run)
   - 7.2 [The PowerPoint tab](#72-the-powerpoint-tab-choose-and-order-slides)
8. [Config Manager](#8-config-manager)
   - 8.1 [What Is the Config Manager?](#81-what-is-the-config-manager)
   - 8.2 [Built-in charts vs. your own folder](#82-built-in-charts-vs-your-own-folder)
   - 8.3 [Editing](#83-editing)

---

## Quick Run (recommended)

The **🚀 Quick Run** tab opens first and covers a normal job on one page. No config folder is needed, because the default charts, colours and PowerPoint template are built into the app.

1. **Test schedule:** pick your event schedule (CSV or Excel `.xlsx`). It needs the columns *Test Description, Test ID, Date, Start Time, End Time* (and optionally *Normalized Time*). A title block above the header row is fine. The plot window (*Plot from / to*) is filled in from the schedule: the first event's start to the last event's end. Type other times if you need a different window.
2. **Analyser data:** pick the folder that holds your analyser exports. Each file is listed with its brand (**Fluke** or **Hioki**); files in mixed brands can sit in the same folder. Choose the **system wiring**:
   - **3-phase 4-wire (with N):** Voltage and THD charts show phase-to-neutral (AN/BN/CN) where the export has it.
   - **3-phase 3-wire (without N):** Voltage and THD charts show line-to-line (AB/BC/CA).

   Hioki exports name their own channels (U1 = phase-to-neutral, U12 = line-to-line), so they are always labelled correctly. If an export only has total power / PF (no per-phase values), those two charts are skipped for that file and listed after the run.
3. **Charts & output:** pick an output folder and, optionally, a **PowerPoint template** (.pptx — remembered; **Use built-in** goes back to the bundled one). Tick the charts you want, and set **Y min / Y max** per chart. Switch on **Auto Y** to fit the axis to the data. The **Unit** column sets the display unit for power (W/kW/MW), voltage (V/kV), current (A/kA) and frequency (Hz/kHz). **Auto** chooses it for you: from the Y limits, or with Auto Y on, from the largest reading across all files, so every image of that chart uses the same unit. Y min / Y max are typed in the unit shown next to them; changing the unit converts them (1500 kW → 1.5 MW). Power factor and THD % have no unit to scale.
4. Click **▶ Generate charts**. Charts appear in the **🔍 Results** tab as they are drawn. When the run finishes you can **View results**, **Open folder**, **Build PowerPoint** or **Download ZIP**.

If a data file has no readings inside the plot window, a ⚠ warning names it after the run. This usually means the wrong schedule or the wrong day's data.

Everything you choose (folders, event file, charts, Y limits) is remembered for next time. Click **↺ Reset Y limits** to go back to the defaults. The **Results**, **PowerPoint** and **Config Manager** tabs are explained below.

---

## 1. Overview

**Trend Graph Software (Elec)** is an internal data visualisation tool for electrical engineers and analysts. It lets you:

- Plot composite trend charts (voltage, current, power factor, frequency, THD, etc.) from raw data files
- Overlay Gantt-style event timelines on your charts
- Export charts directly into a formatted PowerPoint presentation
- Run batch jobs to process multiple data files at once

The app runs entirely on your local machine — no internet connection is required after setup.

---

## 2. Getting Started

### 2.1 What You Need

Before you begin, make sure you have:

- A Windows PC (Windows 10 or later)

*No installation is required — the app runs as a standalone `.exe` file.*

---

### 2.2 Downloading from SharePoint

1. Open the team SharePoint site and navigate to the **Trend Graph Software** folder.(https://bbengsb1.sharepoint.com/:f:/s/BlueBlubEngineeringSdnBhd383/IgDdsYKIl4pwSqMeZd-KbTP2AZMS1zWq3eU2O9fmrGyV45w?e=0hTvac)
2. Download both files:
   - `TrendGraph_v1.0.1.exe` — the application
   - `configs.zip` — the configuration and template bundle

> **Tip:** If you are unsure where the SharePoint folder is, ask your team lead for the link.

---

### 2.3 Setting Up Your Folders

1. Create a folder on your PC where you want to keep the app — for example:
   ```
   C:\Users\YourName\TrendGraph\
   ```
2. Move `TrendGraph_v1.0.1.exe` into that folder.
3. Extract `configs.zip` into the **same folder**. After extraction you should see:
   ```
   TrendGraph\
   ├── TrendGraph_v1.0.1.exe
   ├── 5_configs\
   │   ├── charts\
   │   └── events\
   ├── 6_templates\
   │   └── output.pptx
   │   └── PQA_Template.pptx
   └── 7_samples
   │   └── batch data\
   │   └── events\
   ```

> **Important:** Ensure you have these 3 folders which is `configs`,`templates`,`samples (or actual data)`. It must follow this format but can stored in anywhere

<img src="images/folder_structure.png" width="400">
---

### 2.4 Launching the App

1. Double-click `TrendGraph_v1.0.1.exe`.
2. A black console window may appear briefly — this is normal.

![Folder picker dialog](folder_picker_dialog.png)

3. A **folder picker dialog** will appear asking you to select your config folder.

![Main page of UI](main_page.png)

4. Navigate to your `TrendGraph` folder and select **`5_configs`**.
5. Click **Select Folder**.
6. The app will open in your default web browser automatically (usually at `http://127.0.0.1:8050`).

> **Note:** The app runs locally in your browser. You do not need an internet connection and no data is sent anywhere.

---

## 3. Config Folder Setup

### 3.1 What Is the Config Folder?

The config folder (`5_configs`) contains JSON files that tell the app **how to draw each chart** — which signals to plot, what colours to use, axis labels, and more. Think of each JSON file as a "recipe" for a specific chart type.

You should not need to edit these files for day-to-day use. If a chart needs to be changed or a new one added, you do so with the `Config Manager` feature in the software. As a standard practice, it is recommended to have 1 folder of configs for each project.

---

### 3.2 Folder Structure

Inside `5_configs` you will find two sub-folders:

| Folder | Contents |
|---|---|
| `charts\` | JSON configs for trend/composite charts (voltage, current, etc.) |
| `events\` | JSON config for the Gantt / events chart |

Each JSON file in `charts\` corresponds to one chart type available in the app.

---

### 3.3 Pointing the App to Your Config Folder

Set the folder once in **⚙️ Config Manager** (Browse, or **Copy built-in charts to a folder…** to start from the defaults). It is remembered between sessions, and Quick Run uses it until you click **Use built-in charts**. See section 8.2.

---

## 4. Viewing Results

### 4.1 The Results Tab

The **🔍 Results** tab shows every chart from the last Quick Run. Charts appear there while the run is still drawing, so you can start checking before it finishes. Quick Run's **🔍 View results** button opens the tab once a run is done.

- **◀ ▶** (or the ← → keys) step through the charts. Click a thumbnail in the strip to jump to it.
- **All data files / All charts** narrow the set, for example to one meter or to every Voltage chart.
- **Interactive** redraws the chart on show as a zoomable chart (pan, box-zoom, hover values, camera icon to save). It uses exactly the same time window, Y limits and units as the saved image.
- **Open a folder of images…** loads PNGs from any folder (for example an earlier run) for viewing only. Interactive is not available for these images.
- **Run log** (collapsed at the bottom) holds the full log of the last run, including the reason any chart failed.

> **Tip:** Sample data is in `7_samples\batch_data\` and a sample schedule in `7_samples\events\` if you want to try the app.

---

## 5. Chart Order

Charts are drawn, and slides are built, in the order of the chart list in **⚙️ Config Manager**. Use the **▲ ▼** buttons on a chart row to move it. The order is saved straight away (to `batch_profile.json` in the config folder), and Quick Run's chart table follows it.

Which charts are drawn on a run is chosen with the **Draw** ticks on the Quick Run tab.

---

## 6. Event Colours (Gantt bars)

The coloured bars and labels across the top of each chart come from the test schedule. Their colours are set in **⚙️ Config Manager → 🏷 Event colours**:

- **Test ID colour mappings**: a fixed colour for a Test ID (e.g. `HLT7`).
- **Default palette**: colours given in turn to Test IDs that have no mapping.
- **Bar alpha / height / edge**: how strong the bars look.

Where they are saved:

- **With a config folder chosen:** as `gantt.json` in that folder, so everyone using the folder gets the same event colours.
- **With the built-in charts:** for this PC only (`%APPDATA%\TrendGraph\gantt.json`).

A config folder's `gantt.json` wins over this PC's colours, which win over the built-in ones. Changes apply to the next run; no restart needed.

---

## 7. PowerPoint Export

### 7.1 Straight after a run

On Quick Run, click **📑 Build PowerPoint** under the results. It puts every image from the run into the template, one per slide in chart order, and saves `<schedule>_Charts.pptx` in the output folder.

### 7.2 The PowerPoint tab (choose and order slides)

1. **Slides**: the images from the last run are listed. Untick any you don't want, use **▲ ▼** to change the order, or **Select all / Select none**. Choose **Images in a folder** to use PNGs from somewhere else.
2. **Template & file**: the template is the one Quick Run remembers. Click **Change…** to pick another, or **Use built-in**. The file name is filled in from the schedule.
3. **More options** (rarely needed): save to a different folder, slide DPI, and whether slides are resized to the image shape.
4. Click **📑 Build PowerPoint**. When it is done, a **⬇ Download** link appears. If something goes wrong, open **PowerPoint log**.

---

## 8. Config Manager

### 8.1 What Is the Config Manager?

The Config Manager is one list of every settings file, with a short summary on each row. Click a row to edit it in the panel on the right.

| Row | What it controls | Summary shown |
|---|---|---|
| 🎨 **Global style** | Image size, DPI, fonts, grid, legend spacing for *all* charts (`aesthetics.json`) | size · dpi · font · grid |
| 🏷 **Event colours** | Colours of the test-schedule bars (see section 6) | Test IDs coloured · palette |
| 📈 **Each chart** | Series colours and styles, title, axis labels, *default* Y range | metric · number of series · default Y range |

Each setting has one home:

- **Draw this chart or not**: Quick Run's *Draw* ticks.
- **Chart order**: ▲ ▼ in this list.
- **Y range**: the chart's default lives here, and Quick Run can override it for a run (↺ Reset Y limits goes back to the default).
- **Image size, fonts, grid**: Global style.

> **Caution:** Changes affect everyone who uses the same config folder.

### 8.2 Built-in charts vs. your own folder

With the folder box empty, Quick Run uses the **built-in charts**, which can be viewed but not changed. To customise them:

1. Click **Copy built-in charts to a folder…** and pick an empty folder (for example on SharePoint for your team).
2. The folder becomes the config folder, and Quick Run uses it from then on.
3. **Use built-in charts** switches back at any time.

### 8.3 Editing

- **Edit a chart**: click its row, change the fields, click **💾 Save**. **↺ Revert** reloads the file.
- **New chart**: **➕ New chart**, enter a file name, fill in the series, **💾 Save**. New charts go to the end of the order.
- **Clone / Delete**: buttons in the editor header when a chart is selected. Delete asks for confirmation.

Charts with a **metric** (all built-in charts) pick their data columns automatically for the export brand and wiring. Their series are colour/style slots in phase order, and saving keeps the metric.
