"""Every data file parses: real validation, since a broken data file is a bug. Judged per format (the registry's
formats with a parser) in each unit of the project whose files are in it."""

from __future__ import annotations

from project_validator.facts.wellformed import parsed_formats
from project_validator.judging import answered_check
from project_validator.policy.wellformed import judge_wellformed
from project_validator.questions.wellformed import wellformed_files

data_wellformed = answered_check(
    name="data-wellformed",
    description="Every data file is well formed: it parses in its format (JSON, TOML, YAML and XML are built in)",
    languages=parsed_formats,
    answers=wellformed_files,
    judge=judge_wellformed,
)
