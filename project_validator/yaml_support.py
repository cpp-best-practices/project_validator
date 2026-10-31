"""Optional PyYAML support; everything that needs YAML degrades gracefully when it is missing."""

import importlib
from types import ModuleType


class YamlError(Exception):
    pass


def _import_yaml() -> ModuleType | None:
    try:
        return importlib.import_module("yaml")
    except ImportError:
        return None


_yaml = _import_yaml()


def available() -> bool:
    return _yaml is not None


def load(text: str) -> object:
    if _yaml is None:
        raise YamlError("PyYAML is not available")
    try:
        return _yaml.safe_load(text)
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
