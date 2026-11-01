#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the CHANGELOG.md entry for a version, for the GitHub release notes.

usage: release_notes.py VERSION
Exits with an error when there is no entry, so a release cannot go out
without notes.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def notes(version):
    text = CHANGELOG.read_text()
    match = re.search(rf"^## {re.escape(version)}\b.*?\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else None


if __name__ == "__main__":
    version = sys.argv[1]
    entry = notes(version)
    if not entry:
        sys.exit(f"CHANGELOG.md has no entry for {version}")
    print(entry)
