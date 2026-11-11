"""Discovery of checks and CI providers from the built-in packages and from extra plugin directories."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from project_validator import checks, ci
from project_validator.ci import CiProvider
from project_validator.components import add_plugin_modules
from project_validator.core import Check
from project_validator.ecosystems import Ecosystem, RegistryError, register


class PluginError(Exception):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Plugins:
    checks: tuple[Check, ...]
    providers: tuple[CiProvider, ...]


def _package_modules(package: ModuleType) -> Iterator[ModuleType]:
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda module: module.name):
        yield importlib.import_module(f"{package.__name__}.{info.name}")


def _load_file(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"project_validator_plugin_{path.stem}_{abs(hash(path))}", path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot load plugin {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise PluginError(f"plugin {path} failed to load: {error}") from error
    return module


def _directory_modules(directory: Path) -> Iterator[ModuleType]:
    if not directory.is_dir():
        raise PluginError(f"plugin directory {directory} does not exist")
    yield from map(_load_file, sorted(directory.glob("*.py")))


def _instances[T](modules: Iterable[ModuleType], kind: type[T]) -> list[T]:
    return [value for module in modules for value in vars(module).values() if isinstance(value, kind)]


def _reject_duplicates(kind: str, names: list[str]) -> None:
    if duplicates := sorted({name for name in names if names.count(name) > 1}):
        raise PluginError(f"duplicate {kind}(s): {', '.join(duplicates)}")


def _register_all(ecosystems: list[Ecosystem]) -> None:
    _reject_duplicates("ecosystem label", [ecosystem.label for ecosystem in ecosystems])
    for ecosystem in ecosystems:
        try:
            register(ecosystem)
        except RegistryError as error:
            raise PluginError(str(error)) from error


def discover(plugin_directories: Iterable[Path] = ()) -> Plugins:
    """The checks and CI providers, built in and in the plugin directories; a plugin's ecosystems are registered, and
    its components (tools, settings readers, expanders, actions) made known."""
    plugin_modules = [module for directory in plugin_directories for module in _directory_modules(directory)]
    modules = [*_package_modules(checks), *_package_modules(ci), *plugin_modules]
    _register_all(list(dict.fromkeys(_instances(modules, Ecosystem))))
    add_plugin_modules(plugin_modules)
    found_checks = list(dict.fromkeys(_instances(modules, Check)))
    _reject_duplicates("check name", [found.name for found in found_checks])
    providers = tuple(dict.fromkeys(_instances(modules, CiProvider)))
    return Plugins(checks=tuple(found_checks), providers=providers)
