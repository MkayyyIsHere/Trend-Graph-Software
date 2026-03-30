"""
build.py  —  run this from the repo root to produce the .exe
Usage:  python build.py
Output: 8_dist/TrendGraph_v<version>.exe
"""

import subprocess
import shutil
import sys
from pathlib import Path

# ── Read version ──────────────────────────────────────────────────
VERSION = Path("version.txt").read_text().strip()
APP_NAME = f"TrendGraph_v{VERSION}"
DIST_DIR = Path("8_dist")

print(f"Building {APP_NAME} ...")

# ── Run PyInstaller ───────────────────────────────────────────────
result = subprocess.run(
    [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",                   # single .exe
        "--windowed",                  # no console window (remove if you want a console)
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--add-data", "5_configs;5_configs",    # bundle config files
        "--add-data", "6_templates;6_templates", # bundle templates
        "main.py",
    ],
    check=False
)

if result.returncode != 0:
    print("\nBuild FAILED. Check the output above for errors.")
    sys.exit(1)

# ── Clean up PyInstaller leftovers ────────────────────────────────
shutil.rmtree("build", ignore_errors=True)
spec_file = Path(f"{APP_NAME}.spec")
if spec_file.exists():
    spec_file.unlink()

print(f"\nDone!  →  {DIST_DIR / APP_NAME}.exe")
print("Next: copy this .exe to SharePoint/Releases/latest/")