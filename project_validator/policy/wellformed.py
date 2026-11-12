"""The wellformed policy: every data file of the product (its docs' and tooling's too) parses; a test suite's
malformed data and files too large to read are reported, not judged."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.questions.wellformed import WellformedAnswer


def _files(count: int, format_: str) -> str:
    return f"{count} {format_} file{'s' * (count != 1)}"


def judge_wellformed(answer: WellformedAnswer, *, allow_unknown: bool = False) -> Result:
    """Every judged file must parse. Nothing is unknown here (the validator reads the files itself), so
    `allow_unknown` changes nothing."""
    noted = (
        *(f"test data, not judged: {problem}" for problem in answer.test_problems),
        *(f"{path}: not parsed, {why}" for path, why in answer.unread.items()),
    )
    if answer.problems:
        count = len(answer.problems)
        verb = "does" if count == 1 else "do"
        return Result.failed(f"{_files(count, answer.language)} {verb} not parse", *answer.problems, *noted)
    if not answer.parsed:
        return Result.passed(f"no {answer.language} file to parse", *noted)
    count = len(answer.parsed)
    return Result.passed(f"{_files(count, answer.language)} parse{'s' * (count == 1)}", *noted)


__all__ = ["judge_wellformed"]
