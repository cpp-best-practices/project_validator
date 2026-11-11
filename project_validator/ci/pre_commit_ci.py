"""pre-commit.ci: a CI service that runs a repository's pre-commit hooks on every pull request.

A `.pre-commit-config.yaml` with a `ci:` section is configured for it. Its one job runs `pre-commit run --all-files`,
skipping the hooks `ci.skip` names (as pre-commit's SKIP variable does).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from project_validator import yaml_support
from project_validator.ci import CiProvider, Load
from project_validator.evidence import PRE_COMMIT_CONFIGURATION
from project_validator.facts import CiJob, Command, Fact, Origin
from project_validator.text import pattern

_JOB = "pre-commit.ci"


def _configured(text: str) -> bool:
    """Whether a pre-commit configuration has a `ci:` section."""
    try:
        document = yaml_support.load(text)
    except yaml_support.YamlError:
        return False
    return isinstance(document, Mapping) and "ci" in document


def _facts(path: str, document: object, _load: Load) -> Iterator[Fact]:
    section = document.get("ci") if isinstance(document, Mapping) else None
    settings = section if isinstance(section, Mapping) else {}
    skip = settings.get("skip")
    skipped = ",".join(map(str, skip)) if isinstance(skip, list) else ""
    origin = Origin(path=path, at=("ci",))
    yield CiJob(origin=origin, id=_JOB, provider=PRE_COMMIT_CI.name, name=_JOB, os="linux", builds=False)
    yield Command(
        origin=origin,
        job=_JOB,
        argv=("pre-commit", "run", "--all-files"),
        line="pre-commit run --all-files",
        env={"SKIP": skipped} if skipped else {},
    )


PRE_COMMIT_CI = CiProvider(
    name="pre-commit.ci",
    files=PRE_COMMIT_CONFIGURATION,
    badges=(pattern("pre-commit.ci", r"results\.pre-commit\.ci/badge/"),),
    facts=_facts,
    recognises=_configured,
)
