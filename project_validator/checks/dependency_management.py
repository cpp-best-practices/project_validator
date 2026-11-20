"""Dependencies come from a package manager and are locked, rather than copied into the repository."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import PurePosixPath

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
    vendored = [
        f"{name}/"
        for name in VENDOR_DIRECTORIES
        if name in top_level and name not in generated and _holds_code(context, name)
    ]
    return [*vendored, *((f"git submodules ({SUBMODULES})",) if _submodules(context) else ())]


# What third-party code ships beside it that is not code: notices, licenses and readmes.
_NOTICES = re.compile(r"(?:LICEN[CS]E|COPYING|NOTICE|README|AUTHORS|PATENTS)(?:[-._].*)?", re.IGNORECASE)


def _holds_code(context: Context, directory: str) -> bool:
    """Whether a vendor directory holds more than notices (golangci-lint's third_party/ of license files does not)."""
    inside = (path for path in context.tracked_files if path.startswith(f"{directory}/"))
    return any(not _NOTICES.fullmatch(PurePosixPath(path).name) for path in inside)


_SUBMODULE = re.compile(r"\[submodule\b[^\]]*\]([^\[]*)")
_URL = re.compile(r"^\s*url\s*=\s*(\S+)", re.MULTILINE)
# The host and owner of a repository URL: https://host/owner/repo, ssh://git@host/owner/repo, git@host:owner/repo.
_OWNER = re.compile(r"^(?:[\w+]+://)?(?:[^@/]+@)?([^/:]+)[:/]+([^/]+)/")


def _owner(url: str) -> tuple[str, str] | None:
    found = _OWNER.match(url)
    return (found[1].lower(), found[2].lower()) if found else None


def _submodules(context: Context) -> bool:
    """Whether `.gitmodules` declares a submodule of another's (kubespray's is empty): one whose URL is relative, or
    of the same host and owner as the checkout's origin, is the project's own (xmlunit's test-resources)."""
    if not context.project.exists(SUBMODULES):
        return False
    own = _owner(origin) if (origin := context.project.origin_url()) else None
    for section in _SUBMODULE.findall(context.project.read_text(SUBMODULES)):
        url = found[1] if (found := _URL.search(section)) else ""
        if not url.startswith(("../", "./")) and (own is None or _owner(url) != own):
            return True
    return False


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
