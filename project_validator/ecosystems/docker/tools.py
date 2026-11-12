"""The tools of Dockerfiles: hadolint lints them (and its security rules scan them); checkov, trivy and KICS scan
them for misconfigurations; trivy, grype and Docker Scout audit the packages of the image CI builds."""

from __future__ import annotations

from collections.abc import Mapping

from project_validator.ecosystems.docker import DOCKERFILE_ONLY
from project_validator.facts import Command, resolved
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.arguments import option_values, program
from project_validator.facts.audit import audited, auditor
from project_validator.facts.expansion import Action
from project_validator.facts.security import scanned, scanner
from project_validator.facts.settings import SettingsReader
from project_validator.facts.tools import combined, defined_by, starts, when
from project_validator.tools.misconfiguration import misconfiguration_scanners

# --- hadolint -------------------------------------------------------------------------------------------------------


def _hadolint_configuration(command: Command) -> list[str]:
    argv = resolved(command)
    return option_values(argv, "--config", "-c") if program(argv) == "hadolint" else []


HADOLINT_SETTINGS = SettingsReader(
    name="hadolint", files=(".hadolint.yaml", ".hadolint.yml"), named_by=_hadolint_configuration
)
_HADOLINT_RUNS = starts(("hadolint",))
# hadolint's rules include security ones: a non-root USER (DL3002), pinned versions, no `latest` tag, no sudo.
HADOLINT = combined(
    analyzer(
        name="hadolint",
        languages=DOCKERFILE_ONLY,
        how="hadolint Dockerfile (or hadolint/hadolint-action)",
        analyses=when(_HADOLINT_RUNS, analysed),
        rules=defined_by(files=(HADOLINT_SETTINGS.name,)),
    ),
    scanner(
        name="hadolint",
        languages=DOCKERFILE_ONLY,
        how="hadolint Dockerfile (its security rules: a non-root USER, pinned versions)",
        scans=when(_HADOLINT_RUNS, scanned),
    ),
)


def _hadolint_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`hadolint/hadolint-action` lints its `dockerfile` input (Dockerfile by default) with its `config`."""
    configuration = ("--config", inputs["config"]) if inputs.get("config") else ()
    return (("hadolint", *configuration, inputs.get("dockerfile", "Dockerfile")),)


HADOLINT_ACTION = Action(name="hadolint/hadolint-action", runs=_hadolint_action)

MISCONFIGURATION_SCANNERS = misconfiguration_scanners(DOCKERFILE_ONLY)


# --- the image's packages -------------------------------------------------------------------------------------------

TRIVY_IMAGE = auditor(
    name="trivy",
    languages=DOCKERFILE_ONLY,
    how="trivy image <image> (or aquasecurity/trivy-action, which scans an image unless told otherwise)",
    audits=when(starts(("trivy", "image"), ("trivy", "i")), audited),
)
GRYPE = auditor(
    name="grype",
    languages=DOCKERFILE_ONLY,
    how="grype <image> (or anchore/scan-action)",
    audits=when(starts(("grype",)), audited),
)
DOCKER_SCOUT = auditor(
    name="Docker Scout",
    languages=DOCKERFILE_ONLY,
    how="docker scout cves <image> (or docker/scout-action)",
    audits=when(starts(("docker", "scout", "cves"), ("docker", "scout", "quickview")), audited),
)
GRYPE_ACTION = Action(
    name="anchore/scan-action",
    runs=lambda inputs: (("grype", inputs.get("image") or inputs.get("path") or inputs.get("sbom") or "."),),
)


def _scout_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`docker/scout-action` runs its `command` input (one or more, comma-separated; `quickview` by default) on its
    `image`."""
    commands = inputs.get("command", "quickview").split(",")
    return tuple(("docker", "scout", command.strip(), inputs.get("image", "")) for command in commands)


SCOUT_ACTION = Action(name="docker/scout-action", runs=_scout_action)
# The build shows a job works with the ecosystem (`Ecosystem.ci_programs`), whichever action builds the image.
BUILD_PUSH_ACTION = Action(
    name="docker/build-push-action",
    runs=lambda inputs: (("docker", "buildx", "build", inputs.get("context", ".")),),
)
