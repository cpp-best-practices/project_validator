"""Dependency auditors of many ecosystems at once: osv-scanner, trivy, snyk and GitLab Dependency Scanning. Each knows
the languages whose lockfiles it reads (`OSV_SCANNER_LANGUAGES`, ...); a profile asks for the auditors of its languages
(`multi_ecosystem_audits`) and gets those that read one of them, for those languages only."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping

from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import starts_with
from project_validator.facts.audit import audited, auditor
from project_validator.facts.expansion import Action
from project_validator.facts.tools import Run, Tool, starts, when

_TRIVY_FILESYSTEM = frozenset({"fs", "filesystem", "repo", "repository"})


def _trivy(command: Command, _facts: Facts) -> Run | None:
    """trivy scanning the checkout (`trivy fs .`), not an image."""
    argv = resolved(command)
    return audited() if starts_with(argv, *(("trivy", scans) for scans in _TRIVY_FILESYSTEM)) else None


def _gitlab_dependency_scanning(command: Command, _facts: Facts) -> Run | None:
    argv = resolved(command)
    template = argv[:1] == ("gitlab-template",) and any("Dependency-Scanning" in word for word in argv)
    return audited() if template else None


# The languages whose lockfiles each auditor reads: npm's, pip's and poetry's, go.sum, Cargo.lock, Maven's and Gradle's,
# NuGet's, Composer's, Bundler's, Swift's. pubspec.lock is read by osv-scanner and trivy; mix.lock by those and snyk; an
# sbt build by snyk and GitLab only; nothing reads rebar.lock.
_LOCKFILE_LANGUAGES = frozenset(
    {"JavaScript", "TypeScript", "Python", "Go", "Rust", "Java", "Kotlin", "C#", "F#", "PHP", "Ruby", "Swift"}
)
OSV_SCANNER_LANGUAGES = _LOCKFILE_LANGUAGES | {"Dart", "Elixir"}
TRIVY_LANGUAGES = _LOCKFILE_LANGUAGES | {"Dart", "Elixir"}
SNYK_LANGUAGES = _LOCKFILE_LANGUAGES | {"Scala", "Elixir"}
GITLAB_DEPENDENCY_SCANNING_LANGUAGES = _LOCKFILE_LANGUAGES | {"Scala"}


def _gitlab(read: frozenset[str]) -> Tool:
    return auditor(
        name="GitLab Dependency Scanning",
        languages=read,
        how="GitLab Dependency Scanning (Security/Dependency-Scanning.gitlab-ci.yml)",
        audits=_gitlab_dependency_scanning,
    )


def _osv_scanner(read: frozenset[str]) -> Tool:
    return auditor(
        name="osv-scanner", languages=read, how="osv-scanner", audits=when(starts(("osv-scanner",)), audited)
    )


def _trivy_fs(read: frozenset[str]) -> Tool:
    return auditor(name="trivy", languages=read, how="trivy fs", audits=_trivy)


def _snyk(read: frozenset[str]) -> Tool:
    return auditor(name="snyk", languages=read, how="snyk test", audits=when(starts(("snyk", "test")), audited))


_AUDITORS: tuple[tuple[frozenset[str], Callable[[frozenset[str]], Tool]], ...] = (
    (GITLAB_DEPENDENCY_SCANNING_LANGUAGES, _gitlab),
    (OSV_SCANNER_LANGUAGES, _osv_scanner),
    (TRIVY_LANGUAGES, _trivy_fs),
    (SNYK_LANGUAGES, _snyk),
)


def multi_ecosystem_audits(languages: frozenset[str]) -> tuple[Tool, ...]:
    """GitLab Dependency Scanning, osv-scanner, trivy (of the file system) and snyk, each as an auditor of those of
    `languages` whose lockfiles it reads; an auditor that reads none of them is left out."""
    return tuple(make(read) for reads, make in _AUDITORS if (read := languages & reads))


OSV_SCANNER_ACTION = Action(
    name="google/osv-scanner-action/osv-scanner-action",
    runs=lambda inputs: (("osv-scanner", *shlex.split(inputs.get("scan-args", "-r ./"))),),
)
_TRIVY_SCAN_TYPES = {
    "image": ("image",),
    "config": ("config",),
    "fs": ("fs",),
    "filesystem": ("fs",),
    "repo": ("repo",),
    "repository": ("repo",),
    "rootfs": ("rootfs",),
    "sbom": ("sbom",),
}


def _trivy_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`aquasecurity/trivy-action`: `trivy <scan-type> [--scanners …] <ref>`, an image scan (of `image-ref`) unless
    told the scan type, which scans `scan-ref`."""
    words = _TRIVY_SCAN_TYPES.get(inputs.get("scan-type", "image"))
    if words is None:
        return ()
    scanners = ("--scanners", inputs["scanners"]) if inputs.get("scanners") else ()
    reference = inputs.get("image-ref", ".") if words == ("image",) else inputs.get("scan-ref", ".")
    return (("trivy", *words, *scanners, reference),)


TRIVY_ACTION = Action(name="aquasecurity/trivy-action", runs=_trivy_action)
SNYK_ACTIONS = tuple(
    Action(name=f"snyk/actions/{flavour}", runs=lambda inputs: (("snyk", *shlex.split(inputs.get("command", "test"))),))
    for flavour in ("node", "python", "golang", "gradle", "maven", "php", "ruby", "dotnet", "swift", "cocoapods")
)
