"""The schema-declared policy: every schema of the product (its docs' and tooling's too) declares its dialect and
identifier; one that declares a superseded dialect warns; a test suite's undeclared schemas are reported, not
judged."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.questions import Answer
from project_validator.questions.declaration import DeclarationAnswer


def _files(count: int, format_: str) -> str:
    return f"{count} {format_} file{'s' * (count != 1)}"


def _own(count: int) -> str:
    return "its" if count == 1 else "their"


def judge_schema_declared(answer: DeclarationAnswer, *, allow_unknown: bool = False) -> Result:
    """Every judged schema must declare what its format asks (`what`). Nothing is unknown here (the validator reads
    the schemas itself), so `allow_unknown` changes nothing."""
    if answer.answer is Answer.IMPOSSIBLE:
        return Result.skipped(f"no {answer.language} file declares anything")
    noted = tuple(f"test data, not judged: {problem}" for problem in answer.test_problems)
    if answer.problems:
        undeclared = len({problem.rsplit(": no ", 1)[0] for problem in answer.problems})
        verb = "does" if undeclared == 1 else "do"
        message = f"{_files(undeclared, answer.language)} {verb} not declare {_own(undeclared)} {answer.what}"
        return Result.failed(message, *answer.problems, *answer.outdated, *noted)
    if not answer.declared:
        return Result.passed(f"no {answer.language} file to judge", *noted)
    count = len(answer.declared)
    message = f"{_files(count, answer.language)} declare{'s' * (count == 1)} {_own(count)} {answer.what}"
    if answer.outdated:
        old = len(answer.outdated)
        superseded = f"{_files(old, answer.language)} declare{'s' * (old == 1)} a superseded {answer.what.split()[0]}"
        return Result.warned(superseded, *answer.outdated, *noted)
    return Result.passed(message, *noted)


__all__ = ["judge_schema_declared"]
