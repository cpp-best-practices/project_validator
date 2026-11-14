"""The coverage services a job uploads its report to, Codecov and Coveralls, by their actions and their uploaders:
a measurement uploaded there is reported. Codecov fails a pull request's status under the target its configuration
sets (`coverage.status.project.<name>.target`), which gates it."""

from __future__ import annotations

import re

from project_validator.facts.settings import SettingsReader, matched_settings

UPLOAD_ACTIONS = ("codecov/codecov-action", "coverallsapp/github-action")
UPLOADERS = frozenset({"codecov", "codecovcli", "coveralls", "coveralls-lcov"})
CODECOV = "Codecov"
CODECOV_TARGET = "status target"
_TARGET = re.compile(r"^\s*target\s*:\s*['\"]?(?:auto|\d)", re.MULTILINE)

CODECOV_SETTINGS = SettingsReader(
    name=CODECOV,
    files=("codecov.yml", ".codecov.yml", ".github/codecov.yml", ".github/.codecov.yml"),
    read=lambda path, text: matched_settings(CODECOV, path, text, {CODECOV_TARGET: (_TARGET, True)}),
)

__all__ = ["CODECOV", "CODECOV_SETTINGS", "CODECOV_TARGET", "UPLOADERS", "UPLOAD_ACTIONS"]
