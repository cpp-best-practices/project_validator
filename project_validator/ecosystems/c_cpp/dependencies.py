"""C and C++ dependency managers: CPM, FetchContent, vcpkg, Conan and Meson wraps. None of them has a lockfile, and
C and C++ have no package manager of their own, so each is suggested to a project that declares no dependencies."""

import re
from collections.abc import Iterator

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Fact, Origin
from project_validator.facts.dependencies import Declared, Lock, PackageManager, manifest_reader
from project_validator.facts.settings import SettingsReader
from project_validator.text import strip_cmake_comments

_CMAKE_MANAGERS = {
    "CPM": re.compile(r"\bCPM(?:AddPackage|FindPackage|DeclarePackage)\b|\bCPM\.cmake\b"),
    "FetchContent": re.compile(r"\bFetchContent_(?:Declare|MakeAvailable|Populate)\b"),
}


def _read_cmake_dependencies(path: str, text: str) -> Iterator[Fact]:
    """The CMake dependency managers a CMake file calls, comments left out, until CMake is read structurally."""
    code = strip_cmake_comments(text)
    for manager, calls in _CMAKE_MANAGERS.items():
        if calls.search(code):
            yield Declared(origin=Origin(path=path), manager=manager)


CMAKE_DEPENDENCIES = SettingsReader(
    name="CMake dependencies", files=("CMakeLists.txt", "*.cmake"), read=_read_cmake_dependencies
)


def _declares(_path: str, _text: str) -> bool:
    return True


VCPKG_MANIFESTS = manifest_reader(name="vcpkg manifest", manager="vcpkg", files=("vcpkg.json",), declares=_declares)
CONAN_MANIFESTS = manifest_reader(
    name="Conan recipe", manager="Conan", files=("conanfile.txt", "conanfile.py"), declares=_declares
)
MESON_WRAPS = manifest_reader(
    name="Meson wraps", manager="Meson wraps", files=("subprojects/*.wrap",), declares=_declares
)

C_FAMILY_PACKAGE_MANAGERS = tuple(
    PackageManager(name=name, languages=C_FAMILY, lock=Lock.NEVER, suggested=True)
    for name in ("CPM", "FetchContent", "vcpkg", "Conan", "Meson wraps")
)
