"""The language ecosystems the validator knows, one profile module each, and judging a project per ecosystem."""

from collections.abc import Callable, Mapping
from pathlib import Path

from project_validator.core import Check, Context, Result
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.model import (
    C_FAMILY,
    BuildSystem,
    Ecosystem,
    ToolchainAxis,
    ToolchainPatterns,
    check_each_ecosystem,
    ecosystems_for,
    languages_of,
    toolchain_versions,
)
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST

ECOSYSTEMS = (C_AND_CXX, PYTHON, RUST)

BUILD_SYSTEMS = tuple(build_system for ecosystem in ECOSYSTEMS for build_system in ecosystem.build_systems)


def rules_of[R](kind: type[R]) -> Mapping[Ecosystem, R]:
    """The rule of type `kind` of every ecosystem that has one, in registry order."""
    return {ecosystem: rule for ecosystem in ECOSYSTEMS if (rule := ecosystem.rule(kind)) is not None}


type Judge[R] = Callable[[R, Context], Result]


def practice[R](*, name: str, description: str, rule: type[R]) -> Callable[[Judge[R]], Check]:
    """Turn a judge of one ecosystem's rule into a check of every ecosystem that has a rule of type `rule`.

    The check applies to those ecosystems' languages, and judges each one the project uses (see
    `check_each_ecosystem`).
    """

    def wrap(judge: Judge[R]) -> Check:
        rules = rules_of(rule)

        def run(context: Context) -> Result:
            return check_each_ecosystem(context, rules, judge)

        return Check(name=name, description=description, run=run, languages=languages_of(rules))

    return wrap


def is_build_tree(directory: Path) -> bool:
    """Whether `directory` holds the output of a build, which is never part of the project's sources."""
    return any(system.is_build_tree(directory) for system in BUILD_SYSTEMS if system.is_build_tree is not None)


__all__ = [
    "BUILD_SYSTEMS",
    "C_AND_CXX",
    "C_FAMILY",
    "ECOSYSTEMS",
    "PYTHON",
    "RUST",
    "BuildSystem",
    "Ecosystem",
    "ToolchainAxis",
    "ToolchainPatterns",
    "check_each_ecosystem",
    "ecosystems_for",
    "is_build_tree",
    "languages_of",
    "practice",
    "rules_of",
    "toolchain_versions",
]
