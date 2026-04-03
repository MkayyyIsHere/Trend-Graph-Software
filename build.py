"""
build.py  —  run this from the repo root to produce the .exe
Usage:  python build.py
Output: 8_dist/TrendGraph_v<version>.exe

NOTE: 5_configs and 6_templates are NOT bundled in the .exe.
Distribute them separately on SharePoint as a zip alongside the .exe.
Users select their config folder at runtime via the app's folder picker.
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

REPO_ROOT = str(Path(".").resolve())

SPEC_CONTENT = """# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hidden = []
# ── Internal app packages ─────────────────────────────────────────
hidden += collect_submodules('app')
hidden += collect_submodules('backend')
hidden += collect_submodules('utils')
# ── Dash + UI ─────────────────────────────────────────────────────
hidden += collect_submodules('dash')
hidden += collect_submodules('dash_bootstrap_components')
hidden += collect_submodules('dash_core_components')
hidden += collect_submodules('dash_html_components')
hidden += collect_submodules('dash_table')
# ── Plotly ────────────────────────────────────────────────────────
hidden += collect_submodules('plotly')
# ── Web server ────────────────────────────────────────────────────
hidden += collect_submodules('flask')
hidden += collect_submodules('werkzeug')
# ── Data / file handling ──────────────────────────────────────────
hidden += collect_submodules('pandas')
hidden += collect_submodules('numpy')
hidden += collect_submodules('python_pptx')
hidden += collect_submodules('pptx')
hidden += collect_submodules('PIL')
hidden += collect_submodules('kaleido')

# ── Source folders only — configs and templates are external ──────
# 5_configs and 6_templates are NOT bundled here.
# They are distributed separately on SharePoint as a zip.
# Users select their config folder at runtime via the folder picker.
datas = [
    ('1_app',     '1_app'),
    ('2_backend', '2_backend'),
    ('3_utils',   '3_utils'),
    ('4_assets',  '4_assets'),
]
datas += collect_data_files('dash')
datas += collect_data_files('dash_bootstrap_components')
datas += collect_data_files('plotly')

a = Analysis(
    ['main.py'],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # change to False once fully working
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
""".replace("REPO_ROOT", repr(REPO_ROOT)).replace("APP_NAME", repr(APP_NAME))

spec_path = Path(f"{APP_NAME}.spec")
spec_path.write_text(SPEC_CONTENT, encoding="utf-8")
print(f"Written {spec_path}")

# ── Delete old .exe if exists (avoid Windows permission error) ────
old_exe = DIST_DIR / f"{APP_NAME}.exe"
if old_exe.exists():
    try:
        old_exe.unlink()
        print(f"Removed old {old_exe}")
    except PermissionError:
        print(f"\nERROR: Cannot delete {old_exe}")
        print("Close the running .exe first, then run build.py again.")
        spec_path.unlink(missing_ok=True)
        sys.exit(1)

# ── Run PyInstaller ───────────────────────────────────────────────
result = subprocess.run(
    [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", str(DIST_DIR),
        "--workpath", "build",
        str(spec_path),
    ],
    check=False
)

if result.returncode != 0:
    print("\nBuild FAILED. Check the output above for errors.")
    sys.exit(1)

# ── Clean up PyInstaller leftovers ────────────────────────────────
shutil.rmtree("build", ignore_errors=True)
spec_path.unlink(missing_ok=True)

print(f"\nDone!  ->  {DIST_DIR / APP_NAME}.exe")
print("Next steps:")
print(f"  1. Copy 8_dist/TrendGraph_v{VERSION}.exe  → SharePoint/Releases/latest/")
print("  2. Copy 5_configs/ + 6_templates/          → SharePoint/Releases/latest/configs.zip")