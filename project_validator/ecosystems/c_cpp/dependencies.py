"""C and C++ dependency managers: vcpkg and Conan. Neither has a lockfile, and C and C++ have no package manager of
their own, so each is suggested to a project that declares no dependencies. CMake's (CPM, FetchContent) and Meson's
(wraps) are the build systems' own (see `project_validator.build_systems`)."""

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts.dependencies import Lock, PackageManager, manifest_reader


def _declares(_path: str, _text: str) -> bool:
    return True


VCPKG_MANIFESTS = manifest_reader(name="vcpkg manifest", manager="vcpkg", files=("vcpkg.json",), declares=_declares)
CONAN_MANIFESTS = manifest_reader(
    name="Conan recipe", manager="Conan", files=("conanfile.txt", "conanfile.py"), declares=_declares
)

C_FAMILY_PACKAGE_MANAGERS = tuple(
    PackageManager(name=name, languages=C_FAMILY, lock=Lock.NEVER, suggested=True) for name in ("vcpkg", "Conan")
)
