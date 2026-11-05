"""C and C++ dependency managers: CPM, FetchContent, vcpkg, Conan and Meson wraps. None of them is a lockfile."""

from project_validator.core import Context
from project_validator.ecosystems.c_cpp.compiler_flags import build_texts
from project_validator.rules import DependencyManagement
from project_validator.text import joined, matching_names, pattern

MANAGER_COMMANDS = (
    pattern("CPM", r"\bCPM(?:AddPackage|FindPackage|DeclarePackage)\b|\bCPM\.cmake\b"),
    pattern("FetchContent", r"\bFetchContent_(?:Declare|MakeAvailable|Populate)\b"),
)
MANAGER_FILES = {
    "vcpkg": ("vcpkg.json",),
    "Conan": ("conanfile.txt", "conanfile.py"),
}


def _managers(context: Context) -> str | None:
    found = matching_names(build_texts(context), MANAGER_COMMANDS)
    found += [name for name, files in MANAGER_FILES.items() if any(map(context.project.exists, files))]
    if context.project.files_in("subprojects", (".wrap",)):
        found.append("Meson wraps")
    return f"managed with {joined(found)}" if found else None


DEPENDENCIES = DependencyManagement(
    managed=_managers,
    hint="if the project has dependencies, consider a dependency manager: CPM, FetchContent, vcpkg, Conan or Meson "
    "wraps",
)
