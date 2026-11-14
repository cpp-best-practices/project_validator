"""The wellformed policy: every data file of the product (its docs' and tooling's too) parses; a test suite's
malformed data and files too large to read are reported, not judged."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from project_validator.core import Result
from project_validator.questions.wellformed import WellformedAnswer


def _files(count: int, format_: str) -> str:
    return f"{count} {format_} file{'s' * (count != 1)}"


def _unread(unread: Mapping[str, str], format_: str) -> Iterator[str]:
    """Why files were not parsed: a file alone is named, the files that share a reason (a chart's templates) are
    counted."""
    by_reason: dict[str, list[str]] = {}
    for path, why in unread.items():
        by_reason.setdefault(why, []).append(path)
    for why, paths in by_reason.items():
        what = paths[0] if len(paths) == 1 else _files(len(paths), format_)
        yield f"{what}{':' * (len(paths) == 1)} not parsed, {why}"


def judge_wellformed(answer: WellformedAnswer, *, allow_unknown: bool = False) -> Result:
    """Every judged file must parse. Nothing is unknown here (the validator reads the files itself), so
    `allow_unknown` changes nothing."""
    noted = (
        *(f"test data, not judged: {problem}" for problem in answer.test_problems),
        *_unread(answer.unread, answer.language),
    )
    if answer.problems:
        count = len(answer.problems)
        verb = "does" if count == 1 else "do"
        return Result.failed(f"{_files(count, answer.language)} {verb} not parse", *answer.problems, *noted)
    if not answer.parsed and answer.test_data:
        return Result.passed(f"{_files(len(answer.test_data), answer.language)} of test data, not judged", *noted)
    if not answer.parsed and answer.unread:
        return Result.passed(f"{_files(len(answer.unread), answer.language)} not parsed", *noted)
    if not answer.parsed:
        return Result.passed(f"no {answer.language} file to parse", *noted)
    count = len(answer.parsed)
    return Result.passed(f"{_files(count, answer.language)} parse{'s' * (count == 1)}", *noted)


__all__ = ["judge_wellformed"]
