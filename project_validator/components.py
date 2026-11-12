"""Components (command expanders, actions, settings readers, tools, questions) are found in the modules that define
them, never listed.

A built-in component lives in a module of the shared build systems (`project_validator.build_systems`), the shared
tools (`project_validator.tools`), the questions (`project_validator.questions`), or the profile of the only language
that uses it (see docs/architecture.md). A plugin's components live in its own module (see `add_plugin_modules`).
"""

from __future__ import annotations

import importlib
import pkgutil
import weakref
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from functools import cache
from types import ModuleType
from typing import Any, cast

# The packages whose modules may define components, besides the profiles.
_PACKAGES = (
    "project_validator.build_systems",
    "project_validator.ci",
    "project_validator.tools",
    "project_validator.questions",
)
# Plugin modules, by name: a plugin loaded again replaces its earlier module.
_plugins: dict[str, ModuleType] = {}


def _built_in_modules() -> Iterator[ModuleType]:
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


# Every cache of what is computed from the known components, cleared together (see `component_cache`).
_caches: weakref.WeakSet[Any] = weakref.WeakSet()


def component_cache[**P, R](compute: Callable[P, R]) -> Callable[P, R]:
    """`functools.cache` for what is computed from the known components or ecosystems (the tools of an aspect, the
    languages a check judges, the ecosystems it applies to): computed once, until they change (a plugin is loaded,
    an ecosystem is registered, a test isolates them), when `forget` clears every such cache."""
    cached = cache(compute)
    _caches.add(cached)
    return cast("Callable[P, R]", cached)


def forget() -> None:
    """Forget everything computed from the known components and ecosystems: they have changed."""
    for cached in _caches:
        cached.cache_clear()


def add_plugin_modules(modules: Iterable[ModuleType]) -> None:
    """Make the components the plugin `modules` define known, alongside the built-in ones."""
    _plugins.update((module.__name__, module) for module in modules)
    forget()


@contextmanager
def isolated_plugins() -> Iterator[None]:
    """Undo, on leaving, every plugin module added inside (for tests)."""
    saved = dict(_plugins)
    try:
        yield
    finally:
        _plugins.clear()
        _plugins.update(saved)
        forget()


@component_cache
def known[T](kind: type[T]) -> tuple[T, ...]:
    """Every component of type `kind` a built-in module or a plugin module defines."""
    modules = (*_built_in_modules(), *_plugins.values())
    # A module may define a family of components as a tuple (one analyzer per NuGet package).
    found = (
        item
        for module in modules
        for value in vars(module).values()
        for item in (value if isinstance(value, tuple) else (value,))
    )
    # A component imported by several modules is found once; components need not be hashable.
    return tuple({id(value): value for value in found if isinstance(value, kind)}.values())


__all__ = ["add_plugin_modules", "component_cache", "forget", "isolated_plugins", "known"]
