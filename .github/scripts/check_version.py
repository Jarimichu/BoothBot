"""Fails the release build if the pushed tag doesn't match boothbot/__init__.py's __version__ -
catches the "forgot to bump the version before tagging" mistake before it publishes a mismatched
release. Usage: python check_version.py v1.7.2"""
import re
import sys
from pathlib import Path

tag = sys.argv[1]
tag_version = tag.lstrip("v")

content = Path("boothbot/__init__.py").read_text(encoding="utf-8")
match = re.search(r'__version__ = "([^"]+)"', content)
py_version = match.group(1) if match else None

if py_version != tag_version:
    print(f"::error::Tag {tag} does not match boothbot/__init__.py version {py_version!r} - bump the version before tagging.")
    sys.exit(1)

print(f"Version check passed: tag {tag} matches boothbot/__init__.py ({py_version})")
