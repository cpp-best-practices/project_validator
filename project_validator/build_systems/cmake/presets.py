"""CMake presets (`CMakePresets.json`, `CMakeUserPresets.json`): the cache variables each configure preset sets, with
those it inherits, in the builds configured with it (and on the hosts its condition allows)."""

import json
import posixpath
from collections.abc import Iterator, Mapping

from project_validator.build_systems.cmake.commands import variable_facts
from project_validator.build_systems.cmake.conditions import PLATFORM
from project_validator.facts import Fact, Origin, Unknown
from project_validator.facts.conditions import ALWAYS, NEVER, Condition, both, either, negated, requiring

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")
_HOST = "${hostSystemName}"

type Preset = Mapping[str, object]


def _value(value: object) -> str | None:
    """A cache variable's value: a string, a boolean, or `{"type": ..., "value": ...}`; None unsets it."""
    if isinstance(value, Mapping):
        value = value.get("value")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return None if value is None else str(value)


def _inherited(preset: Preset) -> list[str]:
    inherits = preset.get("inherits", [])
    return (
        [inherits]
        if isinstance(inherits, str)
        else [name for name in inherits if isinstance(name, str)]
        if isinstance(inherits, list)
        else []
    )


def _variables(name: str, presets: Mapping[str, Preset], seen: frozenset[str] = frozenset()) -> dict[str, str | None]:
    """A preset's cache variables: its own over those it inherits, the first preset it inherits from first."""
    if name in seen or name not in presets:
        return {}
    found: dict[str, str | None] = {}
    for parent in reversed(_inherited(presets[name])):
        found |= _variables(parent, presets, seen | {name})
    own = presets[name].get("cacheVariables", {})
    return found | ({key: _value(value) for key, value in own.items()} if isinstance(own, Mapping) else {})


_UNKNOWN_CONDITION = "the preset's condition"
_HOST_TESTS = ("equals", "notEquals", "inList", "notInList")


def _host(condition: Mapping[str, object], kind: str) -> Condition:
    """`equals`, `notEquals`, `inList` or `notInList` of `${hostSystemName}`: the platforms it allows."""
    hosts = [condition.get("rhs")] if kind in ("equals", "notEquals") else condition.get("list")
    allowed = PLATFORM.listed(str(host) for host in hosts) if isinstance(hosts, list) else NEVER
    return negated(allowed) if kind.startswith("not") else allowed


def _combined(condition: Mapping[str, object], kind: object) -> Condition | None:
    """`anyOf`, `allOf` and `not` of other conditions, and `const`; None for another kind."""
    if kind in ("anyOf", "allOf") and isinstance(conditions := condition.get("conditions"), list):
        return (either if kind == "anyOf" else both)(*(_condition(found) for found in conditions))
    if kind == "not":
        return negated(_condition(condition.get("condition")))
    if kind == "const":
        return ALWAYS if condition.get("value") else NEVER
    return None


def _condition(condition: object) -> Condition:
    """The builds a preset's `condition` allows: which host system it is on, as far as it says."""
    if condition is None or isinstance(condition, bool):
        return NEVER if condition is False else ALWAYS
    if not isinstance(condition, Mapping):
        return requiring(_UNKNOWN_CONDITION)
    kind = condition.get("type")
    if isinstance(kind, str) and kind in _HOST_TESTS and _HOST in (condition.get("lhs"), condition.get("string")):
        return _host(condition, kind)
    found = _combined(condition, kind)
    return requiring(_UNKNOWN_CONDITION) if found is None else found


def _presets(path: str, text: str) -> dict[str, Preset]:
    data = json.loads(text)
    presets = data.get("configurePresets", []) if isinstance(data, Mapping) else []
    return {
        preset["name"]: preset
        for preset in presets
        if isinstance(preset, Mapping) and isinstance(preset.get("name"), str)
    }


def preset_facts(files: Mapping[str, str]) -> Iterator[Fact]:
    """The settings of the visible configure presets in `files` (path -> text); the presets of a directory's two files
    inherit from each other."""
    by_directory: dict[str, dict[str, tuple[str, Preset]]] = {}
    for path, text in files.items():
        try:
            found = _presets(path, text)
        except (json.JSONDecodeError, AttributeError) as error:
            yield Unknown(
                origin=Origin(path=path),
                subject="the CMake presets",
                reason=str(error),
                hides="settings",
                tools=("CMake",),
            )
            continue
        by_directory.setdefault(posixpath.dirname(path), {}).update(
            (name, (path, preset)) for name, preset in found.items()
        )
    for named in by_directory.values():
        presets = {name: preset for name, (_, preset) in named.items()}
        for name, (path, preset) in named.items():
            if not preset.get("hidden"):
                builds = both(requiring(f"configured with the {name} preset"), _condition(preset.get("condition")))
                for variable, value in _variables(name, presets).items():
                    if value is not None:
                        origin = Origin(path=path, at=("configurePresets", name, "cacheVariables", variable))
                        yield from variable_facts(origin, variable, value, builds)


__all__ = ["PRESET_FILES", "preset_facts"]
