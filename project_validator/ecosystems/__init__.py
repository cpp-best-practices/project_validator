"""The registry of ecosystems, of languages and of formats (one profile module each, plus plugins' ones).

Every module of this package except `model` is a profile, defining one ecosystem; they are found, not listed.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path
from types import ModuleType

from project_validator.components import component_cache, forget, isolated_plugins
from project_validator.core import Check
from project_validator.ecosystems.model import (
    C_FAMILY,
    BuildSystem,
    Ecosystem,
    Kind,
    ToolchainPatterns,
    ecosystems_for,
    languages_of,
    toolchain_patterns,
)


def _profiles() -> dict[str, Ecosystem]:
    """Profile module name -> the ecosystem it defines, in module name order."""
    modules = sorted(info.name for info in pkgutil.iter_modules(__path__) if info.name != "model")
    found = {name: _defined_in(importlib.import_module(f"{__name__}.{name}")) for name in modules}
    return {name: ecosystem for name, ecosystem in found.items() if ecosystem is not None}


def _defined_in(module: ModuleType) -> Ecosystem | None:
    return next((value for value in vars(module).values() if isinstance(value, Ecosystem)), None)


# The built-in profiles, by module name: a profile's fixtures and documentation are named after its module.
PROFILES = _profiles()
BUILT_IN = tuple(PROFILES.values())

_registered: list[Ecosystem] = list(BUILT_IN)


class RegistryError(Exception):
    pass


def registered() -> tuple[Ecosystem, ...]:
    """Every known ecosystem: the built-in ones, then those registered by plugins, in registration order."""
    return tuple(_registered)


def formats() -> frozenset[str]:
    """The names of every known format: what the format ecosystems' `languages` hold."""
    return languages_of(ecosystem for ecosystem in _registered if ecosystem.kind == "format")


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
    forget()


@contextmanager
def isolated_registry() -> Iterator[None]:
    """Undo, on leaving, every registration made inside, and every plugin's components (for tests)."""
    saved = list(_registered)
    try:
        with isolated_plugins():
            yield
    finally:
        _registered[:] = saved
        forget()


def build_systems() -> tuple[BuildSystem, ...]:
    return tuple(system for ecosystem in _registered for system in ecosystem.build_systems)


@component_cache
def applies_to(selected: Check) -> tuple[str, ...]:
    """The labels of the ecosystems `selected` judges; none for a check that judges every project."""
    if selected.languages:
        return tuple(ecosystem.label for ecosystem in _registered if ecosystem.languages & selected.languages)
    return ()


def is_build_tree(directory: Path) -> bool:
    """Whether `directory` holds the output of a build, which is never part of the project's sources."""
    return any(system.is_build_tree(directory) for system in build_systems() if system.is_build_tree is not None)


__all__ = [
    "BUILT_IN",
    "C_FAMILY",
    "PROFILES",
    "BuildSystem",
    "Ecosystem",
    "Kind",
    "RegistryError",
    "ToolchainPatterns",
    "applies_to",
    "build_systems",
    "claim_conflicts",
    "ecosystems_for",
    "formats",
    "is_build_tree",
    "isolated_registry",
    "languages_of",
    "register",
    "registered",
    "toolchain_patterns",
]
