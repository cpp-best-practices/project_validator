"""Dependencies come from a package manager and are locked, rather than copied into the repository."""

from project_validator.core import Context, Result
from project_validator.ecosystems import check_each_ecosystem, ecosystem_check, rules_of
from project_validator.facts.roles import VENDOR_DIRECTORIES
from project_validator.rules import DependencyManagement

# Top-level directories that usually hold third-party code copied into the repository.
SUBMODULES = ".gitmodules"
VENDOR_HINT = "fetch third-party code with the ecosystem's package manager instead of committing a copy of it"


def _managed(rule: DependencyManagement, context: Context) -> Result:
    managed = rule.managed(context)
    if managed is None:
        return Result.passed("no dependencies are declared", *((rule.hint,) if rule.hint else ()))
    if rule.locked is None or not rule.lock_required(context):
        return Result.passed(f"dependencies are {managed}")
    if locked := rule.locked(context):
        return Result.passed(f"dependencies are {managed} and locked in {locked}")
    return Result.warned(f"dependencies are {managed} but not locked", rule.lock_hint)


def _vendored(context: Context) -> list[str]:
    """Top-level directories of committed third-party code, and git submodules; package manager output is not."""
    outputs = {output for rule in rules_of(DependencyManagement).values() for output in rule.vendor_outputs}
    top_level = {path.partition("/")[0] for path in context.tracked_files if "/" in path}
    generated = {output.partition("/")[0] for output in outputs if context.committed(output)}
    vendored = [f"{name}/" for name in VENDOR_DIRECTORIES if name in top_level and name not in generated]
    return [*vendored, *((f"git submodules ({SUBMODULES})",) if context.project.exists(SUBMODULES) else ())]


@ecosystem_check(
    name="dependency-management",
    description="Dependencies come from a package manager (e.g. CPM, vcpkg, uv, Cargo) and are locked, not vendored",
    rule=DependencyManagement,
)
def dependency_management(context: Context) -> Result:
    managed = check_each_ecosystem(context, rules_of(DependencyManagement), _managed)
    if not (vendored := _vendored(context)):
        return managed
    # Each ecosystem's judgement passes or warns, so vendored code makes the result a warning.
    return Result.warned(
        f"third-party code is committed ({', '.join(vendored)}); {managed.message}", *managed.details, VENDOR_HINT
    )
