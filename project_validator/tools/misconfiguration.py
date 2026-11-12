"""Misconfiguration scanners of infrastructure files (Terraform, Dockerfiles, Kubernetes manifests): checkov, trivy and
KICS read the configuration for insecure settings, which is static analysis and security scanning at once. Each profile
makes them its own for its languages (`misconfiguration_scanners`), adding the commands of its own that run them
(pre-commit-terraform's hooks). trivy's action is `project_validator.tools.audits.TRIVY_ACTION`."""

from __future__ import annotations

import shlex
from collections.abc import Iterable

from project_validator.facts import Command, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, starts_with
from project_validator.facts.expansion import Action
from project_validator.facts.security import scanned, scanner
from project_validator.facts.tools import Condition, Tool, combined, starts, when

_TRIVY_FILESYSTEM = (("trivy", "fs"), ("trivy", "filesystem"), ("trivy", "repo"), ("trivy", "repository"))


def trivy_misconfiguration(command: Command, *also: tuple[str, ...]) -> bool:
    """`trivy config` (or one of the `also` commands, a profile's own that run it), or a filesystem scan whose
    `--scanners` include misconfigurations."""
    argv = resolved(command)
    if starts_with(argv, ("trivy", "config"), *also) is not None:
        return True
    if starts_with(argv, *_TRIVY_FILESYSTEM) is None:
        return False
    return any("misconfig" in value for value in option_values(argv, "--scanners"))


def misconfiguration_scanner(name: str, languages: frozenset[str], how: str, runs: Condition) -> Tool:
    """A misconfiguration scanner of `languages`, which analyses the configuration and scans it for security
    problems: the commands `runs` matches do both."""
    return combined(
        analyzer(name=name, languages=languages, how=how, analyses=when(runs, analysed)),
        scanner(name=name, languages=languages, how=how, scans=when(runs, scanned)),
    )


def misconfiguration_scanners(
    languages: frozenset[str], *, checkov: Iterable[tuple[str, ...]] = (), trivy: Iterable[tuple[str, ...]] = ()
) -> tuple[Tool, ...]:
    """checkov, trivy and KICS as misconfiguration scanners of `languages`; `checkov` and `trivy` name the profile's
    own commands that run each (`("terraform_checkov",)`)."""
    trivy_also = tuple(trivy)
    return (
        misconfiguration_scanner("checkov", languages, "checkov -d .", starts(("checkov",), *checkov)),
        misconfiguration_scanner(
            "trivy", languages, "trivy config .", lambda command: trivy_misconfiguration(command, *trivy_also)
        ),
        misconfiguration_scanner("KICS", languages, "kics scan -p .", starts(("kics", "scan"))),
    )


CHECKOV_ACTION = Action(
    name="bridgecrewio/checkov-action", runs=lambda inputs: (("checkov", "-d", inputs.get("directory", ".")),)
)
KICS_ACTION = Action(
    name="checkmarx/kics-github-action",
    runs=lambda inputs: (("kics", "scan", "-p", *shlex.split(inputs.get("path", "."))),),
)
