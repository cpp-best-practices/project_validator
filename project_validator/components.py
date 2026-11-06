"""Components (command expanders, coverage tools) are found in the modules that define them, never listed.

A component lives in a module of the shared build systems (`project_validator.build_systems`), the shared tools
(`project_validator.tools`), or the profile of the only language that uses it (see docs/architecture.md).
"""

import importlib
import pkgutil
from collections.abc import Iterator
from functools import cache
from types import ModuleType

# The packages whose modules may define components, besides the profiles.
_PACKAGES = ("project_validator.build_systems", "project_validator.tools")


def _modules() -> Iterator[ModuleType]:
    from project_validator.ecosystems import PROFILES

    for package_name in _PACKAGES:
        package = importlib.import_module(package_name)
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda module: module.name):
            yield importlib.import_module(f"{package_name}.{info.name}")
    for name in PROFILES:
        profile = importlib.import_module(f"project_validator.ecosystems.{name}")
        yield profile
        # A profile that is a package keeps its components in its modules.
        for info in sorted(pkgutil.iter_modules(getattr(profile, "__path__", [])), key=lambda module: module.name):
            yield importlib.import_module(f"{profile.__name__}.{info.name}")


@cache
def built_in[T](kind: type[T]) -> tuple[T, ...]:
    """Every component of type `kind` a module of the shared build systems, the shared tools or a profile defines."""
    found = (value for module in _modules() for value in vars(module).values())
    # A component imported by several modules is found once; components need not be hashable.
    return tuple({id(value): value for value in found if isinstance(value, kind)}.values())


__all__ = ["built_in"]
