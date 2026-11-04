"""The registry of language ecosystems (one profile module each, plus plugins' ones), and judging per ecosystem."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from project_validator.core import Check, CheckFunction, Context, Result, Status
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.model import (
    C_FAMILY,
    BuildSystem,
    Ecosystem,
    ToolchainAxis,
    ToolchainPatterns,
    check_each_ecosystem,
    combined,
    ecosystems_for,
    languages_of,
    toolchain_versions,
)
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST

BUILT_IN = (C_AND_CXX, PYTHON, RUST)

_registered: list[Ecosystem] = list(BUILT_IN)


class RegistryError(Exception):
    pass


def registered() -> tuple[Ecosystem, ...]:
    """Every known ecosystem: the built-in ones, then those registered by plugins, in registration order."""
    return tuple(_registered)


def register(ecosystem: Ecosystem) -> None:
    """Add a plugin's ecosystem, replacing a plugin ecosystem with the same label (the same plugin, loaded again).

    A built-in ecosystem is never replaced.
    """
    if ecosystem in _registered:
        return
    if any(built_in.label == ecosystem.label for built_in in BUILT_IN):
        raise RegistryError(f"{ecosystem.label} is a built-in ecosystem")
    replaced = [index for index, known in enumerate(_registered) if known.label == ecosystem.label]
    if replaced:
        _registered[replaced[0]] = ecosystem
    else:
        _registered.append(ecosystem)


@contextmanager
def isolated_registry() -> Iterator[None]:
    """Undo, on leaving, every registration made inside (for tests)."""
    saved = list(_registered)
    try:
        yield
    finally:
        _registered[:] = saved


def build_systems() -> tuple[BuildSystem, ...]:
    return tuple(system for ecosystem in _registered for system in ecosystem.build_systems)


def providers(kind: type[object]) -> tuple[Ecosystem, ...]:
    """The ecosystems that have a rule of type `kind`, their own or one of their build systems'."""
    return tuple(ecosystem for ecosystem in _registered if ecosystem.has_rule(kind))


def rules_of[R](kind: type[R]) -> Mapping[Ecosystem, R]:
    """The ecosystem-wide rule of type `kind` of every ecosystem that has one, in registry order."""
    return {ecosystem: rule for ecosystem in _registered if (rule := ecosystem.rule(kind)) is not None}


def applies_to(selected: Check) -> tuple[str, ...]:
    """The labels of the ecosystems `selected` judges; none for a check that judges every project."""
    if selected.rule is not None:
        return tuple(ecosystem.label for ecosystem in providers(selected.rule))
    if selected.languages:
        return tuple(ecosystem.label for ecosystem in _registered if ecosystem.languages & selected.languages)
    return ()


def with_registered_languages(selected: Check) -> Check:
    """`selected`, applying to the languages of every ecosystem now registered that has its rule."""
    if selected.rule is None:
        return selected
    return replace(selected, languages=languages_of(providers(selected.rule)))


def ecosystem_check(*, name: str, description: str, rule: type[object]) -> Callable[[CheckFunction], Check]:
    """A check of the whole project that applies wherever an ecosystem has a rule of type `rule`."""

    def wrap(function: CheckFunction) -> Check:
        return Check(
            name=name, description=description, run=function, languages=languages_of(providers(rule)), rule=rule
        )

    return wrap


type Judge[R] = Callable[[R, Context], Result]


def judge_ecosystem[R](
    ecosystem: Ecosystem, kind: type[R], judge: Judge[R], context: Context, build_systems: frozenset[str]
) -> Result:
    """`judge` of the ecosystem's rule of type `kind` for `build_systems`; a SKIP when it has none for them."""
    rule = ecosystem.rule_for(kind, build_systems)
    if rule is not None:
        return judge(rule, context)
    used = ", ".join(system.name for system in ecosystem.used_build_systems(build_systems))
    return Result(status=Status.SKIP, message=f"not applicable to {ecosystem.label} built with {used}")


def practice[R](
    *, name: str, description: str, rule: type[R], aliases: tuple[str, ...] = ()
) -> Callable[[Judge[R]], Check]:
    """Turn a judge of one ecosystem's rule into a check of every ecosystem that has a rule of type `rule`.

    The check applies to those ecosystems' languages, and judges each one the project uses (see
    `check_each_ecosystem`) by the rule for the build systems the project uses (see `Ecosystem.rule_for`).
    """

    def wrap(judge: Judge[R]) -> Check:
        def run(context: Context) -> Result:
            structure = context.structure
            used = ecosystems_for(structure.languages, providers(rule))
            return combined(
                {
                    ecosystem: judge_ecosystem(ecosystem, rule, judge, context, structure.build_systems)
                    for ecosystem in used
                }
            )

        languages = languages_of(providers(rule))
        return Check(name=name, description=description, run=run, languages=languages, rule=rule, aliases=aliases)

    return wrap


def is_build_tree(directory: Path) -> bool:
    """Whether `directory` holds the output of a build, which is never part of the project's sources."""
    return any(system.is_build_tree(directory) for system in build_systems() if system.is_build_tree is not None)


__all__ = [
    "BUILT_IN",
    "C_AND_CXX",
    "C_FAMILY",
    "PYTHON",
    "RUST",
    "BuildSystem",
    "Ecosystem",
    "RegistryError",
    "ToolchainAxis",
    "ToolchainPatterns",
    "applies_to",
    "build_systems",
    "check_each_ecosystem",
    "combined",
    "ecosystem_check",
    "ecosystems_for",
    "is_build_tree",
    "isolated_registry",
    "judge_ecosystem",
    "languages_of",
    "practice",
    "providers",
    "register",
    "registered",
    "rules_of",
    "toolchain_versions",
    "with_registered_languages",
]
