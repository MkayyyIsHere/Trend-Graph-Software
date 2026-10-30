"""
scan_project.py
---------------
Scans the folder where this script lives and writes a directory tree
to 'project_structure.txt' in the same folder.

Exclusions:
  - Hidden folders and files (names starting with '.')
  - __pycache__ directories
  - *.pyc / *.pyo files
  - The output file itself (project_structure.txt)
"""

import os
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────

ROOT         = Path(__file__).resolve().parent
OUTPUT_FILE  = ROOT / "project_structure.txt"

EXCLUDED_DIRS = {
    "__pycache__",
}

EXCLUDED_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def is_excluded_dir(name: str) -> bool:
    """Return True if a directory should be skipped."""
    return name.startswith(".") or name in EXCLUDED_DIRS


def is_excluded_file(name: str) -> bool:
    """Return True if a file should be skipped."""
    if name.startswith("."):
        return True
    if name == OUTPUT_FILE.name:
        return True
    if Path(name).suffix.lower() in EXCLUDED_FILE_SUFFIXES:
        return True
    return False


def build_tree(directory: Path, prefix: str = "") -> list[str]:
    """
    Recursively build a list of lines representing the directory tree.
    Uses box-drawing characters for a clean visual layout.
    """
    lines = []

    try:
        entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        lines.append(prefix + "└── [permission denied]")
        return lines

    # Filter entries
    visible = []
    for entry in entries:
        if entry.is_dir() and is_excluded_dir(entry.name):
            continue
        if entry.is_file() and is_excluded_file(entry.name):
            continue
        visible.append(entry)

    for i, entry in enumerate(visible):
        is_last   = (i == len(visible) - 1)
        connector = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "

        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            lines.extend(build_tree(entry, prefix + extension))
        else:
            lines.append(f"{prefix}{connector}{entry.name}")

    return lines


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = [
        f"Project Structure",
        f"Generated : {timestamp}",
        f"Root      : {ROOT}",
        "=" * 60,
        f"{ROOT.name}/",
    ]

    tree_lines = build_tree(ROOT)

    output_lines = header + tree_lines + ["", f"Total entries: {len(tree_lines)}"]
    output_text  = "\n".join(output_lines) + "\n"

    OUTPUT_FILE.write_text(output_text, encoding="utf-8")

    print(f"✓ Structure written to: {OUTPUT_FILE}")
    print(f"  {len(tree_lines)} entries scanned.")


if __name__ == "__main__":
    main()