"""2_backend/batch_profile.py — Batch Profile persistence helper.

A Batch Profile defines which chart config files are included in a batch
run and in what order.  It is stored as a single JSON file alongside the
chart configs in the same folder:

    <config_folder>/batch_profile.json

Schema
------
{
    "ordered_configs": [
        "1_config_composite_Power Factor.json",
        "0_config_composite_Active_Power.json",
        ...
    ]
}

Only filenames (not full paths) are stored so that the profile remains
valid even when the folder is moved.  Files that are present in the
folder but absent from `ordered_configs` are treated as *excluded*.
"""

from __future__ import annotations

import json
import os
from typing import List

from utils.constants import RESERVED_CONFIG_FILENAMES

BATCH_PROFILE_FILENAME = "batch_profile.json"


class BatchProfileManager:
    """Load, save and apply a Batch Profile for a given config folder."""

    def __init__(self, config_folder: str = ""):
        self._folder: str = config_folder
        self._ordered: List[str] = []   # filenames only, in desired order

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def profile_path(self) -> str:
        return os.path.join(self._folder, BATCH_PROFILE_FILENAME) if self._folder else ""

    def load(self, config_folder: str) -> bool:
        """Load the profile from *config_folder*.

        Returns True if a saved profile was found and loaded, False if
        the folder has no profile (caller should fall back to alphabetical
        ordering).
        """
        self._folder  = config_folder
        self._ordered = []

        path = self.profile_path
        if not path or not os.path.isfile(path):
            return False

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("ordered_configs", [])
            if isinstance(entries, list):
                self._ordered = [str(e) for e in entries if str(e).lower().endswith(".json")]
                return True
        except Exception:
            pass
        return False

    def save(self, config_folder: str, ordered_filenames: List[str]) -> bool:
        """Persist *ordered_filenames* to *config_folder*/batch_profile.json.

        Returns True on success.
        """
        self._folder  = config_folder
        self._ordered = list(ordered_filenames)

        path = self.profile_path
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ordered_configs": self._ordered}, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def get_ordered_paths(
        self,
        config_folder: str,
        fallback_alphabetical: bool = True,
    ) -> List[str]:
        """Return a list of *full paths* for config files in the correct order.

        Only files explicitly saved in the profile (i.e. included by the user)
        are returned. Files absent from the saved profile are treated as
        excluded — they are NOT appended as extras. This ensures that toggling
        a config off in the UI actually prevents it from running.

        Reserved files (aesthetics.json, batch_profile.json) are always excluded.

        If no profile has been loaded and *fallback_alphabetical* is True,
        all non-reserved JSON files in the folder are returned in alphabetical order.
        """
        if not config_folder or not os.path.isdir(config_folder):
            return []

        all_json = {
            f for f in os.listdir(config_folder)
            if f.lower().endswith(".json")
            and f not in RESERVED_CONFIG_FILENAMES
        }

        if not self._ordered and fallback_alphabetical:
            return [os.path.join(config_folder, f) for f in sorted(all_json)]

        # Return only files that are in the saved profile AND exist on disk.
        # Files not in the profile were deliberately excluded by the user.
        seen:    set[str]  = set()
        ordered: List[str] = []
        for fname in self._ordered:
            if fname in all_json and fname not in seen:
                ordered.append(os.path.join(config_folder, fname))
                seen.add(fname)

        return ordered

    def get_ordered_filenames(self) -> List[str]:
        """Return the raw ordered filename list (may include stale entries)."""
        return list(self._ordered)

    def merge_with_folder(self, config_folder: str) -> List[dict]:
        """Return a merged list of ``{filename, included}`` dicts for the UI.

        Files in the saved profile appear first in their saved order,
        marked as *included*. Any extra files found on disk that are not
        in the profile are appended at the end, marked as *excluded* —
        new files are opt-in, not opt-out.

        Reserved files (aesthetics.json, batch_profile.json) are always hidden.
        """
        if not config_folder or not os.path.isdir(config_folder):
            return []

        all_json = sorted(
            f for f in os.listdir(config_folder)
            if f.lower().endswith(".json")
            and f not in RESERVED_CONFIG_FILENAMES
        )

        if not self._ordered:
            # No profile yet — treat all files as included in alpha order
            return [{"filename": f, "included": True} for f in all_json]

        seen:   set[str] = set()
        result: List[dict] = []
        for fname in self._ordered:
            if fname in set(all_json) and fname not in seen:
                result.append({"filename": fname, "included": True})
                seen.add(fname)

        # New files not yet in the profile — shown but excluded by default
        for fname in all_json:
            if fname not in seen:
                result.append({"filename": fname, "included": False})

        return result