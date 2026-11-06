"""What a project layout is: a minimal project of one kind, and what it is recognised as."""

from collections.abc import Mapping
from dataclasses import dataclass

from project_validator.ecosystems import C_FAMILY


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectLayout:
    """A kind of project: its build and source files, and the languages and build systems they map to."""

    name: str
    files: Mapping[str, str]
    languages: frozenset[str]
    build_systems: frozenset[str]
    # Checks that apply to the layout's languages but that its profile cannot judge, which it reports as SKIP.
    skipped: frozenset[str] = frozenset()
    # The profile module the layout belongs to, which names its fixtures; set when the layouts are collected.
    profile: str = ""

    @property
    def uses_cmake(self) -> bool:
        return "CMake" in self.build_systems

    @property
    def gets_c_family_checks(self) -> bool:
        """C/C++ checks run for C and C++ projects only."""
        return bool(self.languages & C_FAMILY)
