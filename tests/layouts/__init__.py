"""Kinds of project, one module per profile, named after the profile's module; they are found, not listed."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import replace

from tests.layouts.model import ProjectLayout


def _profile_layouts() -> tuple[ProjectLayout, ...]:
    modules = sorted(info.name for info in pkgutil.iter_modules(__path__) if info.name != "model")
    return tuple(
        replace(layout, profile=name)
        for name in modules
        for layout in importlib.import_module(f"{__name__}.{name}").LAYOUTS
    )


PROFILE_LAYOUTS = _profile_layouts()
UNRECOGNISED = ProjectLayout(
    name="Unrecognised language",
    files={"README.md": "", "src/main.odin": ""},
    languages=frozenset(),
    build_systems=frozenset(),
)
