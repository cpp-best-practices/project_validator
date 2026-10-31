"""PyYAML support; it is required, but imported here so a missing install is reported cleanly instead of crashing."""

import importlib
from types import ModuleType

MISSING_MESSAGE = "PyYAML >= 6.0 is required (python3 -m pip install PyYAML, or the distro's python3-yaml package)"


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
        raise YamlError(MISSING_MESSAGE)
    try:
        return _yaml.safe_load(text)
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
