"""Extracts the CHANGELOG.md section for a given version and writes it to release_notes.md, for
use as the GitHub Release body. Usage: python extract_release_notes.py v1.7.2"""
import re
import sys
from pathlib import Path

tag = sys.argv[1]
version = tag.lstrip("v")

changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
match = re.search(
    rf"^## \[{re.escape(version)}\].*?\n(.*?)(?=\n## \[|\Z)",
    changelog,
    flags=re.MULTILINE | re.DOTALL,
)
notes = match.group(1).strip() if match else "See CHANGELOG.md for details."
notes += "\n\nFull history: https://github.com/Jarimichu/BoothBot/blob/main/CHANGELOG.md"

Path("release_notes.md").write_text(notes, encoding="utf-8")
print(f"Wrote release notes for {tag}:\n{notes}")
