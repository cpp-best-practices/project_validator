"""The C and C++ standards a build sets (upstream #412): CMake's `CMAKE_CXX_STANDARD` (`CMAKE_C_STANDARD`), a target's
`CXX_STANDARD` or `target_compile_features(... cxx_std_20)`, and Meson's `cpp_std` (`c_std`). Shown as the versions of
the language the project supports, beside the compilers CI builds with; never judged."""

from __future__ import annotations

from collections.abc import Iterator

from project_validator.facts import Facts
from project_validator.facts.build import BuildSetting
from project_validator.facts.versions import DeclaredVersion, VersionsDeclared

# The settings that name a standard: the language, and whether the value is the standard's number (CMake's `20`) or
# its name (Meson's `c++20`).
_STANDARDS = {
    "CMAKE_CXX_STANDARD": ("C++", True),
    "CXX_STANDARD": ("C++", True),
    "CMAKE_C_STANDARD": ("C", True),
    "C_STANDARD": ("C", True),
    "cpp_std": ("C++", False),
    "c_std": ("C", False),
}


def _standards(facts: Facts) -> Iterator[DeclaredVersion]:
    for setting in facts.of(BuildSetting):
        if (found := _STANDARDS.get(setting.name)) is None or not setting.value:
            continue
        language, numbered = found
        version = f"{language}{setting.value}" if numbered else setting.value
        yield DeclaredVersion(origin=setting.origin, language=language, version=version)


STANDARDS = VersionsDeclared(name="the C and C++ standards a build sets", read=_standards)

__all__ = ["STANDARDS"]
