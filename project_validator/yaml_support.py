"""PyYAML support; it is required, but imported here so a missing install is reported cleanly instead of crashing."""

import importlib
from types import ModuleType

MISSING_MESSAGE = "PyYAML >= 6.0 is required (python3 -m pip install PyYAML, or the distro's python3-yaml package)"


class YamlError(Exception):
    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        # 1-based, when the parser knows where the problem is.
        self.line = line
        self.column = column


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


def check_documents(text: str) -> None:
    """Parse every document of `text` without constructing values, so any tag (`!reference`, `!Ref`) is accepted:
    only whether the text is well-formed YAML is judged."""
    if _yaml is None:
        raise YamlError(MISSING_MESSAGE)
    try:
        for _ in _yaml.compose_all(text, Loader=_yaml.SafeLoader):
            pass
    except _yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        problem = error.problem or error.context or "invalid YAML"
        raise YamlError(problem, mark.line + 1, mark.column + 1) if mark else YamlError(problem) from error
    except _yaml.YAMLError as error:
        raise YamlError(str(error).replace("\n", " ")) from error
