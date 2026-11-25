"""What the release workflow checks before it builds (upstream #337): the tag is `v<version>`, the package's version is
that version, and CHANGELOG.md has its section. With `--notes FILE`, it writes that section, the release's notes.

    python tests/release_check.py v0.1.0 --notes notes.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def notes(changelog: str, version: str) -> str:
    """The changelog's section for `version` (`## 0.1.0`, up to the next `## `), without its heading; empty when it
    has none."""
    found = re.search(rf"^## {re.escape(version)}[ \t]*\n(.*?)(?=^## |\Z)", changelog, re.MULTILINE | re.DOTALL)
    return found[1].strip() if found else ""


def problems(tag: str, version: str, changelog: str) -> list[str]:
    """Why `tag` can't be released as the package at `version` with `changelog`; none when it can."""
    if not tag.startswith("v"):
        return [f"the tag {tag} is not v<version>"]
    if tag[1:] != version:
        return [f"the tag {tag} is not the package's version, {version}"]
    return [] if notes(changelog, version) else [f"CHANGELOG.md has no section for {version}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that a tag can be released, and write its notes.")
    parser.add_argument("tag")
    parser.add_argument("--notes", type=Path, help="write the release's notes here")
    arguments = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from project_validator import __version__  # the checkout's, not an installed copy

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    found = problems(arguments.tag, __version__, changelog)
    for problem in found:
        print(f"release_check: {problem}", file=sys.stderr)
    if not found and arguments.notes is not None:
        arguments.notes.write_text(notes(changelog, __version__) + "\n", encoding="utf-8")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
