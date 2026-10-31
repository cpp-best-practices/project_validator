"""Helpers for building throw-away projects and contexts in tests."""

import tempfile
import textwrap
import unittest
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from project_validator import yaml_support
from project_validator.core import Context, Options, Project
from project_validator.plugins import discover

FIXTURES = Path(__file__).parent / "fixtures"

requires_yaml = unittest.skipUnless(yaml_support.available(), "PyYAML is not installed")


@contextmanager
def temp_project(files: Mapping[str, str]) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative, contents in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(contents), encoding="utf-8")
        yield root


def make_context(root: Path, **options: object) -> Context:
    return Context(Project(root), discover().providers, Options(**options))
