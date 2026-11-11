"""The dependency management policy: dependencies are declared for a package manager and, where a lock is asked for,
locked."""

from __future__ import annotations

from project_validator.core import Result
from project_validator.policy import either, skipped_or_unknown
from project_validator.policy import files as files_listed
from project_validator.questions.dependencies import DependencyAnswer


def _declared(answer: DependencyAnswer) -> str:
    return f"dependencies are declared in {files_listed(answer.manifests())} ({', '.join(answer.managers())})"


def judge_dependencies(answer: DependencyAnswer, *, allow_unknown: bool = False) -> Result:
    """Declared and locked (or a lock not asked for) passes, as does nothing declared; declared but not locked warns.
    A language no known package manager handles is skipped. An unknown answer is an error unless `allow_unknown`."""
    settled = skipped_or_unknown(
        answer.answer,
        answer.unknowns,
        impossible=f"no known package manager resolves {answer.language} dependencies",
        asks="whether the dependencies are managed and locked",
        allow_unknown=allow_unknown,
    )
    if settled is not None:
        return settled
    if not answer.declared:
        if not answer.suggested:
            return Result.passed("no dependencies are declared")
        suggested = either(answer.suggested)
        return Result.passed(
            "no dependencies are declared",
            f"if the project has dependencies, consider a dependency manager: {suggested}",
        )
    if not answer.lock_required:
        return Result.passed(_declared(answer))
    if answer.locked:
        return Result.passed(f"{_declared(answer)} and locked in {files_listed(answer.locked)}")
    return Result.warned(f"{_declared(answer)} but not locked", *answer.lock_hints)


__all__ = ["judge_dependencies"]
