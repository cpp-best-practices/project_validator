"""Publishing: where CI publishes a release (PyPI, crates.io, npm, a container registry…), whether it does so by
trusted publishing or with provenance, and whether it attaches an SBOM or a provenance attestation (upstream #412).

`DESTINATIONS` says how each destination is published to: by the actions that publish there, and by the commands
(their program and subcommands). This is knowledge of the tools, not a judgement; nothing here is scored.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from project_validator.about.detail import Detail
from project_validator.facts import ActionStep, Command, Facts
from project_validator.facts.arguments import program

type Step = ActionStep | Command


def _unsaid(_step: Step) -> str:
    return ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Destination:
    """Where a release is published: the actions (their repositories) and commands (program and subcommands) that
    publish there, whether an action's step publishes (`publishes`), and what is said of how (`how`)."""

    name: str
    actions: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    publishes: Callable[[ActionStep], bool] = lambda _step: True
    how: Callable[[Step], str] = _unsaid


def _repository(step: ActionStep) -> str:
    return step.uses.partition("@")[0].lower()


def _pypi(step: Step) -> str:
    if isinstance(step, ActionStep):
        return "with a token" if "password" in step.inputs else "with trusted publishing"
    return ""


def _npm(step: Step) -> str:
    provenance = isinstance(step, Command) and (
        "--provenance" in step.argv or step.env.get("NPM_CONFIG_PROVENANCE", "").lower() == "true"
    )
    return "with provenance" if provenance else ""


def _image(step: Step) -> str:
    if not isinstance(step, ActionStep):
        return ""
    attached = [name for name in ("provenance", "sbom") if step.inputs.get(name, "").lower() not in ("", "false")]
    return f"with {' and '.join('an SBOM' if name == 'sbom' else name for name in attached)}" if attached else ""


def _pushes(step: ActionStep) -> bool:
    return step.inputs.get("push", "").lower() == "true"


DESTINATIONS = (
    Destination(
        name="PyPI",
        actions=("pypa/gh-action-pypi-publish",),
        commands=(
            ("twine", "upload"),
            ("uv", "publish"),
            ("poetry", "publish"),
            ("flit", "publish"),
            ("hatch", "publish"),
            ("pdm", "publish"),
        ),
        how=_pypi,
    ),
    Destination(name="crates.io", actions=("katyo/publish-crates",), commands=(("cargo", "publish"),)),
    Destination(
        name="npm",
        actions=("js-devtools/npm-publish",),
        commands=(("npm", "publish"), ("pnpm", "publish"), ("yarn", "npm", "publish")),
        how=_npm,
    ),
    Destination(
        name="RubyGems",
        actions=("rubygems/release-gem",),
        commands=(("gem", "push"),),
        how=lambda step: "with trusted publishing" if isinstance(step, ActionStep) else "",
    ),
    Destination(name="NuGet", commands=(("dotnet", "nuget", "push"), ("nuget", "push"))),
    Destination(name="Maven", commands=(("mvn", "deploy"), ("gradle", "publish"), ("gradlew", "publish"))),
    Destination(name="Hex", commands=(("mix", "hex.publish"),)),
    Destination(name="pub.dev", commands=(("dart", "pub", "publish"), ("flutter", "pub", "publish"))),
    Destination(
        name="a container registry",
        actions=("docker/build-push-action",),
        commands=(("docker", "push"), ("podman", "push")),
        publishes=_pushes,
        how=_image,
    ),
    Destination(
        name="GitHub releases",
        actions=("softprops/action-gh-release", "ncipollo/release-action"),
        commands=(("gh", "release", "create"),),
    ),
)
# What attaches an SBOM or a provenance attestation to a release: by action, and by the program that writes it.
ATTESTATIONS = (
    Destination(
        name="an SBOM",
        actions=("anchore/sbom-action", "actions/attest-sbom"),
        commands=(("syft",), ("cyclonedx-py",), ("cyclonedx-npm",)),
    ),
    Destination(name="provenance", actions=("actions/attest-build-provenance", "slsa-framework/slsa-github-generator")),
)


def _runs(command: Command, prefix: tuple[str, ...]) -> bool:
    return bool(command.argv) and (program(command.argv), *command.argv[1 : len(prefix)]) == prefix


def _steps(destination: Destination, facts: Facts) -> Iterator[tuple[str, Step]]:
    """Each step that publishes to `destination`, with what it is called."""
    for step in facts.of(ActionStep):
        repository = _repository(step)
        named = any(repository == action or repository.startswith(f"{action}/") for action in destination.actions)
        if named and destination.publishes(step):
            yield repository, step
    for command in facts.of(Command):
        if prefix := next((prefix for prefix in destination.commands if _runs(command, prefix)), None):
            yield " ".join(prefix), command


def _said(found: Iterable[tuple[str, Step]], how: Callable[[Step], str]) -> list[str]:
    """`by npm publish (.github/workflows/release.yml), with provenance`, each said once."""
    return list(
        dict.fromkeys(
            f"by {name} ({step.origin.path})" + (f", {said}" if (said := how(step)) else "") for name, step in found
        )
    )


def publishing(facts: Facts) -> Iterator[Detail]:
    """Where CI publishes, destination by destination, then what it attaches."""
    for destination in DESTINATIONS:
        if words := _said(_steps(destination, facts), destination.how):
            yield Detail(group="Publishing", subject=destination.name, text="; ".join(words), data={"by": words})
    attached = [
        f"{attestation.name} {said}"
        for attestation in ATTESTATIONS
        for said in _said(_steps(attestation, facts), _unsaid)
    ]
    if attached:
        yield Detail(group="Publishing", subject="attestations", text="; ".join(attached), data={"attached": attached})


__all__ = ["ATTESTATIONS", "DESTINATIONS", "Destination", "publishing"]
