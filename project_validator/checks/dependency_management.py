"""Dependencies come from a package manager and are locked, rather than copied into the repository."""

from __future__ import annotations

from dataclasses import replace

from project_validator.core import Check, Context, Result, Status
from project_validator.facts.dependencies import known_package_managers
from project_validator.facts.roles import VENDOR_DIRECTORIES
from project_validator.judging import answered_check
from project_validator.policy.dependencies import judge_dependencies
from project_validator.questions.dependencies import dependency_management as dependency_answers

SUBMODULES = ".gitmodules"
VENDOR_HINT = "fetch third-party code with the ecosystem's package manager instead of committing a copy of it"


def _languages() -> frozenset[str]:
    return frozenset().union(*(manager.languages for manager in known_package_managers()))


def _vendored(context: Context) -> list[str]:
    """Top-level directories of committed third-party code, and git submodules; package manager output is not."""
    outputs = {output for manager in known_package_managers() for output in manager.vendor_outputs}
    top_level = {path.partition("/")[0] for path in context.tracked_files if "/" in path}
    generated = {output.partition("/")[0] for output in outputs if context.committed(output)}
    vendored = [f"{name}/" for name in VENDOR_DIRECTORIES if name in top_level and name not in generated]
    return [*vendored, *((f"git submodules ({SUBMODULES})",) if context.project.exists(SUBMODULES) else ())]


def _with_vendored(managed: Check) -> Check:
    """`managed`, warning besides about third-party code committed to the repository."""

    def run(context: Context) -> Result:
        result = managed.run(context)
        # An unknown answer stays an error, whatever is vendored.
        if not (vendored := _vendored(context)) or result.status is Status.ERROR:
            return result
        # Each language's judgement passes or warns, so vendored code makes the result a warning.
        return Result.warned(
            f"third-party code is committed ({', '.join(vendored)}); {result.message}", *result.details, VENDOR_HINT
        )

    return replace(managed, run=run)


dependency_management = _with_vendored(
    answered_check(
        name="dependency-management",
        description="Dependencies come from a package manager (CPM, vcpkg, uv, Cargo) and are locked, not vendored",
        languages=_languages,
        answers=dependency_answers,
        judge=judge_dependencies,
    )
)
