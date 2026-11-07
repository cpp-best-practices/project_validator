"""Dependency auditors of many ecosystems at once: osv-scanner, trivy and snyk. Each profile makes them its own, for its
languages (`multi_ecosystem_audits`), since they audit whatever lockfiles the project has."""

import shlex

from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.expansion import Action
from project_validator.facts.tools import Run, Tool, starts, when

_TRIVY_FILESYSTEM = frozenset({"fs", "filesystem", "repo", "repository"})


def _trivy(command: Command, _facts: Facts) -> Run | None:
    """trivy scanning the checkout (`trivy fs .`), not an image."""
    argv = resolved(command)
    return audited() if program(argv) == "trivy" and argv[1:2] and argv[1] in _TRIVY_FILESYSTEM else None


def multi_ecosystem_audits(languages: frozenset[str]) -> tuple[Tool, ...]:
    """osv-scanner, trivy (of the file system) and snyk, as auditors of `languages`."""
    return (
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
# trivy's action scans an image unless told to scan the file system.
TRIVY_ACTION = Action(
    name="aquasecurity/trivy-action",
    runs=lambda inputs: (("trivy", inputs.get("scan-type", "image"), inputs.get("scan-ref", ".")),),
)
SNYK_ACTIONS = tuple(
    Action(name=f"snyk/actions/{flavour}", runs=lambda inputs: (("snyk", *shlex.split(inputs.get("command", "test"))),))
    for flavour in ("node", "python", "golang", "gradle", "maven", "php", "ruby", "dotnet", "swift", "cocoapods")
)
