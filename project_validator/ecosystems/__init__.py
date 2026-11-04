"""The language ecosystems the validator knows, one profile module each, and judging a project per ecosystem."""

from pathlib import Path

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
    "toolchain_versions",
]
