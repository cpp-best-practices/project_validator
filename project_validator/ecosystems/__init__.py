"""The registry of language ecosystems (one profile module each, plus plugins' ones), and judging per ecosystem."""

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path

from project_validator.core import Check, CheckFunction, Context, Result, Status
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.dotnet import DOTNET
from project_validator.ecosystems.go import GO
from project_validator.ecosystems.javascript import JAVASCRIPT_AND_TYPESCRIPT
from project_validator.ecosystems.jvm import JVM
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
from project_validator.ecosystems.php import PHP
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.ruby import RUBY
from project_validator.ecosystems.rust import RUST

BUILT_IN = (C_AND_CXX, PYTHON, RUST, GO, JAVASCRIPT_AND_TYPESCRIPT, JVM, PHP, RUBY, DOTNET)

_registered: list[Ecosystem] = list(BUILT_IN)


class RegistryError(Exception):
    pass


def registered() -> tuple[Ecosystem, ...]:
    """Every known ecosystem: the built-in ones, then those registered by plugins, in registration order."""
    return tuple(_registered)


def _build_file_claims(ecosystems: Iterable[Ecosystem]) -> Iterator[tuple[str, BuildSystem, Ecosystem]]:
    for ecosystem in ecosystems:
        for system in ecosystem.build_systems:
            for name in system.files:
                yield name, system, ecosystem


def _suffix_claims(ecosystems: Iterable[Ecosystem]) -> Iterator[tuple[str, bool, Ecosystem]]:
    """(suffix, whether it is unambiguous, the ecosystem claiming it)."""
    for ecosystem in ecosystems:
        yield from ((suffix, True, ecosystem) for suffix in ecosystem.source_suffixes or {})
        yield from ((suffix, False, ecosystem) for suffix in ecosystem.ambiguous_suffixes or {})


def claim_conflicts(ecosystems: Iterable[Ecosystem]) -> list[str]:
    """Where `ecosystems` claim the same files: a build file of two build systems (sharing one build system is
    fine), or a source suffix one claims outright and another claims too (two may share an ambiguous suffix)."""
    ecosystems = tuple(ecosystems)
    conflicts = []
    build_files: dict[str, BuildSystem] = {}
    for name, system, ecosystem in _build_file_claims(ecosystems):
        known = build_files.setdefault(name, system)
        if known is not system:
            conflicts.append(f"{ecosystem.label}: build file {name} is already claimed by {known.name}")
        elif clashing := next(
            (other for other, owner in build_files.items() if owner is not system and _globs_overlap(name, other)),
            None,
        ):
            conflicts.append(
                f"{ecosystem.label}: build file {name} overlaps {clashing} of {build_files[clashing].name}"
            )
    claimed: dict[str, tuple[bool, Ecosystem]] = {}
    for suffix, outright, ecosystem in _suffix_claims(ecosystems):
        known_outright, claimant = claimed.setdefault(suffix, (outright, ecosystem))
        if claimant is not ecosystem and (outright or known_outright):
            conflicts.append(f"{ecosystem.label}: source suffix {suffix} is already claimed by {claimant.label}")
    return conflicts


def _globs_overlap(name: str, other: str) -> bool:
    """Whether one build file entry matches the other literally (`*.csproj` and `app.csproj`)."""
    return fnmatchcase(name, other) or fnmatchcase(other, name)


def register(ecosystem: Ecosystem) -> None:
    """Add a plugin's ecosystem, replacing a plugin ecosystem with the same label (the same plugin, loaded again).

    A built-in ecosystem is never replaced, and an ecosystem must not claim another one's files.
    """
    if ecosystem in _registered:
        return
    if any(built_in.label == ecosystem.label for built_in in BUILT_IN):
        raise RegistryError(f"{ecosystem.label} is a built-in ecosystem")
    others = [known for known in _registered if known.label != ecosystem.label]
    if conflicts := [
        conflict for conflict in claim_conflicts([*others, ecosystem]) if conflict.startswith(f"{ecosystem.label}:")
    ]:
        raise RegistryError("; ".join(conflicts))
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


def judge_each_ecosystem[R](context: Context, kind: type[R], judge: Judge[R]) -> Result:
    """`judge` of the rule of type `kind` of each ecosystem the project uses, for the build systems it uses (see
    `judge_ecosystem`): the worst result wins, and findings are labelled."""
    structure = context.structure
    used = ecosystems_for(structure.languages, providers(kind))
    return combined(
        {ecosystem: judge_ecosystem(ecosystem, kind, judge, context, structure.build_systems) for ecosystem in used}
    )


def practice[R](
    *, name: str, description: str, rule: type[R], aliases: tuple[str, ...] = ()
) -> Callable[[Judge[R]], Check]:
    """Turn a judge of one ecosystem's rule into a check of every ecosystem that has a rule of type `rule`.

    The check applies to those ecosystems' languages, and judges each one the project uses (see
    `check_each_ecosystem`) by the rule for the build systems the project uses (see `Ecosystem.rule_for`).
    """

    def wrap(judge: Judge[R]) -> Check:
        def run(context: Context) -> Result:
            return judge_each_ecosystem(context, rule, judge)

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
    "DOTNET",
    "GO",
    "JAVASCRIPT_AND_TYPESCRIPT",
    "JVM",
    "PHP",
    "PYTHON",
    "RUBY",
    "RUST",
    "BuildSystem",
    "Ecosystem",
    "RegistryError",
    "ToolchainAxis",
    "ToolchainPatterns",
    "applies_to",
    "build_systems",
    "check_each_ecosystem",
    "claim_conflicts",
    "combined",
    "ecosystem_check",
    "ecosystems_for",
    "is_build_tree",
    "isolated_registry",
    "judge_each_ecosystem",
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
