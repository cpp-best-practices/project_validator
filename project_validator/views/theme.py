"""The design shared by the HTML report, the documentation site and the leaderboard: one stylesheet, light and dark
(following the system, or chosen with the toggle), with the status colours every view uses (`assets/theme.css`), and
the script that switches the theme and remembers the choice (`assets/theme.js`).

They are files of the package, read once, so that the HTML report stays one self-contained file and needs nothing
installed.
"""

from __future__ import annotations

from importlib.resources import files

_ASSETS = files("project_validator.views") / "assets"


def asset(name: str) -> str:
    """The text of one of the views' assets (`theme.css`, `report.js`)."""
    return (_ASSETS / name).read_text(encoding="utf-8")


STYLESHEET = asset("theme.css")
THEME_SCRIPT = asset("theme.js")

__all__ = ["STYLESHEET", "THEME_SCRIPT", "asset"]
