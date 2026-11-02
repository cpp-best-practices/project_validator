"""Helpers for building throw-away projects and contexts in tests."""

import tempfile
import textwrap
import unittest
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from project_validator import pretty
from project_validator.core import Check, Context, Options, Project, Result
from project_validator.ecosystems import C_AND_CXX, ECOSYSTEMS, Ecosystem, ecosystems_for
from project_validator.plugins import discover
from project_validator.structure import C_FAMILY

FIXTURES = Path(__file__).parent / "fixtures"

requires_rich = unittest.skipUnless(pretty.available(), "rich is not installed")

NO_FILES: Mapping[str, str] = MappingProxyType({})


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


def fixture_files(name: str) -> dict[str, str]:
    directory = FIXTURES / name
    return {
        path.relative_to(directory).as_posix(): path.read_text(encoding="utf-8")
        for path in directory.rglob("*")
        if path.is_file()
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectLayout:
    """A kind of project: its build and source files, and the languages and build systems they map to."""

    name: str
    files: Mapping[str, str]
    languages: frozenset[str]
    build_systems: frozenset[str]

    @property
    def uses_cmake(self) -> bool:
        return "CMake" in self.build_systems

    @property
    def gets_c_family_checks(self) -> bool:
        """C/C++ checks run for C and C++ projects, and for projects whose language is not recognised."""
        return not self.languages or bool(self.languages & C_FAMILY)


# CMake files are deliberately free of project() and settings so that the files a test adds decide what is checked.
PROJECT_LAYOUTS = (
    ProjectLayout(
        name="CMake C++",
        files={"CMakeLists.txt": "", "src/main.cpp": "", "include/app/app.hpp": ""},
        languages=C_FAMILY,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="CMake C",
        files={"CMakeLists.txt": "", "src/main.c": "", "include/app.h": ""},
        languages=C_FAMILY,
        build_systems=frozenset({"CMake"}),
    ),
    ProjectLayout(
        name="CMake C++ with Python bindings",
        files={"CMakeLists.txt": "", "pyproject.toml": "", "src/module.cpp": "", "python/app/__init__.py": ""},
        languages=C_FAMILY | {"Python"},
        build_systems=frozenset({"CMake", "Python packaging"}),
    ),
    ProjectLayout(
        name="Meson C++",
        files={"meson.build": "project('app', 'cpp')\n", "src/main.cpp": ""},
        languages=frozenset({"C++"}),
        build_systems=frozenset({"Meson"}),
    ),
    ProjectLayout(
        name="Meson C",
        files={"meson.build": "project('app', 'c')\n", "src/main.c": ""},
        languages=frozenset({"C"}),
        build_systems=frozenset({"Meson"}),
    ),
    ProjectLayout(
        name="Header-only C++",
        files={"include/app/app.hpp": ""},
        languages=frozenset({"C++"}),
        build_systems=frozenset(),
    ),
    ProjectLayout(
        name="Cargo Rust",
        files={"Cargo.toml": "", "src/main.rs": ""},
        languages=frozenset({"Rust"}),
        build_systems=frozenset({"Cargo"}),
    ),
    ProjectLayout(
        name="Meson Rust",
        files={"meson.build": "project('app', 'rust')\n", "src/main.rs": ""},
        languages=frozenset({"Rust"}),
        build_systems=frozenset({"Meson"}),
    ),
    ProjectLayout(
        name="Python pyproject",
        files={"pyproject.toml": "", "src/app/__init__.py": ""},
        languages=frozenset({"Python"}),
        build_systems=frozenset({"Python packaging"}),
    ),
    ProjectLayout(
        name="Python setup.py",
        files={"setup.py": "", "app/__init__.py": ""},
        languages=frozenset({"Python"}),
        build_systems=frozenset({"Python packaging"}),
    ),
    ProjectLayout(
        name="Unrecognised language",
        files={"README.md": "", "src/main.zig": ""},
        languages=frozenset(),
        build_systems=frozenset(),
    ),
)

def checked_ecosystems(selected: Check, layout: ProjectLayout) -> tuple[Ecosystem, ...]:
    """The ecosystems `selected` judges in a project of `layout`."""
    supported = (ecosystem for ecosystem in ECOSYSTEMS if ecosystem.languages <= selected.languages)
    return ecosystems_for(layout.languages, supported)


def layouts_checked_as(selected: Check, *ecosystems: Ecosystem) -> tuple[ProjectLayout, ...]:
    """Every layout in which `selected` judges exactly `ecosystems`."""
    return tuple(layout for layout in PROJECT_LAYOUTS if checked_ecosystems(selected, layout) == ecosystems)


C_FAMILY_LAYOUTS = tuple(layout for layout in PROJECT_LAYOUTS if layout.gets_c_family_checks)
C_FAMILY_ONLY_LAYOUTS = tuple(layout for layout in C_FAMILY_LAYOUTS if layout.languages <= C_FAMILY)
OTHER_LANGUAGE_LAYOUTS = tuple(layout for layout in PROJECT_LAYOUTS if not layout.gets_c_family_checks)
NON_CMAKE_C_FAMILY_LAYOUTS = tuple(layout for layout in C_FAMILY_LAYOUTS if not layout.uses_cmake)


def _first_config_file(files: tuple[str, ...], directories: tuple[str, ...]) -> str:
    return files[0] if files else f"{directories[0]}/ci.yml"


# CI provider name -> a path its configuration is found at.
CI_FILES = {
    provider.name: _first_config_file(provider.files, provider.directories)
    for provider in discover().providers
    if provider.files or provider.directories
}


@contextmanager
def layout_project(
    test: unittest.TestCase, layout: ProjectLayout, files: Mapping[str, str] = NO_FILES, **sub_test: object
) -> Iterator[Path]:
    """A sub-test on a project of `layout` with `files` added; `files` win over the layout's own files."""
    with test.subTest(layout=layout.name, **sub_test), temp_project({**layout.files, **files}) as root:
        yield root


def run_in_every_layout(
    test: unittest.TestCase,
    selected: Check,
    files: Mapping[str, str],
    layouts: tuple[ProjectLayout, ...] | None = None,
    **options: object,
) -> Result:
    """The result of `selected` in a project of each layout with `files` added, which must not depend on the layout.

    By default the layouts are every one in which `selected` judges only C/C++.
    """
    if layouts is None:
        layouts = layouts_checked_as(selected, C_AND_CXX)
    results: dict[str, Result] = {}
    for layout in layouts:
        with temp_project({**layout.files, **files}) as root:
            results[layout.name] = selected.run(make_context(root, **options))
    expected = results[layouts[0].name]
    for name, result in results.items():
        with test.subTest(layout=name):
            test.assertEqual(result, expected)
    return expected


CODEQL_WORKFLOW = """\
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: python
      - uses: github/codeql-action/analyze@v3
"""

# A Python project that passes every check that applies to Python.
WELL_CONFIGURED_PYTHON: Mapping[str, str] = MappingProxyType(
    {
        "pyproject.toml": "[project]\nname = 'app'\n\n[tool.coverage.run]\nbranch = true\n",
        "tests/test_app.py": "",
        ".github/workflows/codeql.yml": CODEQL_WORKFLOW,
        ".github/workflows/ci.yml": """\
            jobs:
              test:
                runs-on: ${{ matrix.os }}
                strategy:
                  matrix:
                    os: [ubuntu-latest, macos-latest, windows-latest]
                    python: ["3.13", "3.14"]
                steps:
                  - uses: actions/checkout@v4
                  - uses: actions/setup-python@v5
                    with:
                      python-version: ${{ matrix.python }}
                  - run: python -m pip install coverage pytest
                  - run: python -W error -m coverage run -m pytest
        """,
    }
)

# A Rust project that passes every check that applies to Rust.
WELL_CONFIGURED_RUST: Mapping[str, str] = MappingProxyType(
    {
        "Cargo.toml": "[package]\nname = 'app'\n\n[lints.clippy]\npedantic = { level = 'warn', priority = -1 }\n",
        "src/lib.rs": "#[cfg(test)]\nmod tests {\n    #[test]\n    fn works() {}\n}\n",
        ".github/workflows/codeql.yml": CODEQL_WORKFLOW,
        ".github/workflows/ci.yml": """\
            jobs:
              test:
                runs-on: ${{ matrix.os }}
                strategy:
                  matrix:
                    os: [ubuntu-latest, macos-latest, windows-latest]
                    toolchain: [stable, nightly]
                    sanitizer: ["", "-Zsanitizer=address"]
                env:
                  RUSTFLAGS: -D warnings ${{ matrix.sanitizer }}
                steps:
                  - uses: actions/checkout@v4
                  - uses: dtolnay/rust-toolchain@master
                    with:
                      toolchain: ${{ matrix.toolchain }}
                  - run: cargo clippy --all-targets
                  - run: cargo test
                  - run: cargo test --release
                  - run: cargo llvm-cov --branch --mcdc
        """,
    }
)
