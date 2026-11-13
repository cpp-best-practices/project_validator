"""Dependency auditors of many ecosystems at once: osv-scanner, trivy and snyk. Each profile makes them its own, for its
languages (`multi_ecosystem_audits`), since they audit whatever lockfiles the project has."""

from __future__ import annotations

import shlex
from collections.abc import Mapping

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


def multi_ecosystem_audits(languages: frozenset[str]) -> tuple[Tool, ...]:
    """osv-scanner, trivy (of the file system), snyk and GitLab Dependency Scanning, as auditors of `languages`."""
    return (
        auditor(
            name="GitLab Dependency Scanning",
            languages=languages,
            how="GitLab Dependency Scanning (Security/Dependency-Scanning.gitlab-ci.yml)",
            audits=_gitlab_dependency_scanning,
        ),
        auditor(
            name="osv-scanner", languages=languages, how="osv-scanner", audits=when(starts(("osv-scanner",)), audited)
        ),
        auditor(name="trivy", languages=languages, how="trivy fs", audits=_trivy),
        auditor(name="snyk", languages=languages, how="snyk test", audits=when(starts(("snyk", "test")), audited)),
    )


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
