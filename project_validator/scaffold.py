"""Start a built-in ecosystem: `python -m project_validator.scaffold <module> <Label> <suffix>...` writes what
the ecosystem contract asks for (see tests/test_ecosystem_contract.py), so that only the language's knowledge is
left to write:

- the profile, a package `project_validator/ecosystems/<module>/`: `__init__.py` with the ecosystem, recognised by
  its source suffixes and its CI toolchain (guessed from the module name: a `setup-<module>` action with a
  `<module>-version` input, a `<module>` container image), and `tools.py` and `practices.py` for its components;
- the project layouts the checks are run in, `tests/layouts/<module>.py`;
- the fixtures: `tests/fixtures/well_configured_<module>`, from the files every project has (a license, a security
  policy, Dependabot, CI that lints itself and detects copy-paste), and `tests/fixtures/bare_<module>`;
- the documentation page, `docs/ecosystems/<module>.md`.

Nothing is overwritten. Then: fix the toolchain's patterns, add the language's components, its source files and CI to
the fixtures, a section of the page for each check that applies to it, and the snapshots (`UPDATE_SNAPSHOTS=1
python -m unittest tests.test_snapshots`).
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

# The files of a well-configured project that are not about its language, from the Go fixture.
_SHARED = (
    "LICENSE",
    "README.md",
    "SECURITY.md",
    ".github/dependabot.yml",
    ".github/workflows/ci-lint.yml",
    ".github/workflows/copy-paste-detection.yml",
)
_TEMPLATE = "tests/fixtures/well_configured_go"

_PROFILE = '''"""{label}: recognised by its sources ({suffixes}), and by the toolchain its CI names.

A profile is a package whose modules each define components, found rather than listed (see docs/architecture.md):
here the ecosystem and its build systems (`BuildSystem`, with the files they are recognised by and the build types
their commands build) and toolchain axis (`versions_axis`, or a `ToolchainAxis` of compilers); in `tools.py` the
tools; in `practices.py` the practices. Package managers (`PackageManager`, `manifest_reader`, `lockfile_reader`),
the declared license (`declared_license_reader`) and build outputs (`BuildOutput`) go where they read best.
"""

from project_validator.ecosystems.model import Ecosystem, toolchain_patterns

{constant}_LANGUAGE = frozenset({{"{label}"}})

{constant} = Ecosystem(
    label="{label}",
    languages={constant}_LANGUAGE,
    source_suffixes={source_suffixes},
    # How a CI job names the toolchain's version, or shows it uses one; guessed from the module name: check each.
    toolchain=toolchain_patterns(
        "{label}",
        inputs=("{module}-version",),
        images=("{module}",),
        commands=r"\\b{module}\\s+(?:build|test|run)\\b",
        setup=("{module}",),
    ),
)
'''

_TOOLS = '''"""{label}'s tools, each a component found here: test runners (`test_runner`, with the `TestFiles` that
define tests), coverage (`coverage_tool`), formatters (`format_tool`), analyzers (`analyzer`), type checkers
(`type_checker`), security scanners (`scanner`), auditors (`auditor`) and function length limiters (`limiter`), from
`project_validator.facts.*`. A tool claims the commands that run it (`when(starts(...), ...)`, see
`project_validator.facts.tools`); the settings files it reads are `SettingsReader`s."""
'''

_PRACTICES = '''"""{label}'s practices, each a `Practice` found here (see `project_validator.facts.practices`): the
strict warning set (`WARNINGS`), warnings as errors (`WARNINGS_AS_ERRORS`), hardening (`HARDENING`). A compiled
language's are compiler flags: `warning_requirements`, `errors_requirements` and `flag_requirements` from
`project_validator.facts.flags`. Each practice's `Wording` says what its settings are called and how to set them."""
'''

_LAYOUTS = '''"""Kinds of {label} project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="{label} sources",
        files={{"src/main{suffix}": ""}},
        languages=frozenset({{"{label}"}}),
        build_systems=frozenset(),
    ),
)
'''

_PAGE = """# {label}

Recognised by {suffixes} sources.

<!-- A section (## `check-name`) for each check that applies to {label}, saying what it accepts. -->
"""


def _files(module: str, label: str, suffixes: Sequence[str]) -> dict[str, str]:
    constant = re.sub(r"\W", "_", module).upper()
    listed = ", ".join(f"`{suffix}`" for suffix in suffixes)
    mapping = "{" + ", ".join(f'"{suffix}": "{label}"' for suffix in suffixes) + "}"
    package = f"project_validator/ecosystems/{module}"
    return {
        f"{package}/__init__.py": _PROFILE.format(
            label=label, suffixes=listed, constant=constant, source_suffixes=mapping, module=module
        ),
        f"{package}/tools.py": _TOOLS.format(label=label),
        f"{package}/practices.py": _PRACTICES.format(label=label),
        f"tests/layouts/{module}.py": _LAYOUTS.format(label=label, suffix=suffixes[0]),
        f"docs/ecosystems/{module}.md": _PAGE.format(label=label, suffixes=listed),
        f"tests/fixtures/bare_{module}/src/main{suffixes[0]}": "",
        f"tests/fixtures/well_configured_{module}/src/main{suffixes[0]}": "",
    }


def scaffold(root: Path, module: str, label: str, suffixes: Sequence[str]) -> list[Path]:
    """Write the new ecosystem's files under `root` (a checkout of the project); the paths written."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", module) or not suffixes or not all(s.startswith(".") for s in suffixes):
        raise ValueError("expected a module name (lower case) and source suffixes starting with '.'")
    written: list[Path] = []
    targets = {**_files(module, label, suffixes)}
    fixture = root / f"tests/fixtures/well_configured_{module}"
    for name in _SHARED:
        targets[str((fixture / name).relative_to(root))] = (root / _TEMPLATE / name).read_text(encoding="utf-8")
    existing = [path for path in targets if (root / path).exists()]
    if existing:
        raise FileExistsError(f"already there: {', '.join(existing)}")
    for path, text in targets.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m project_validator.scaffold", description=__doc__.split("\n")[0])
    parser.add_argument("module", help="the profile's module name, e.g. haskell")
    parser.add_argument("label", help="the ecosystem's label, e.g. Haskell")
    parser.add_argument("suffixes", nargs="+", help="its source suffixes, e.g. .hs .lhs")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="the project checkout (default: here)")
    arguments = parser.parse_args(argv)
    try:
        written = scaffold(arguments.root, arguments.module, arguments.label, arguments.suffixes)
    except (ValueError, FileExistsError) as error:
        print(f"scaffold: {error}", file=sys.stderr)
        return 2
    for path in written:
        print(path.relative_to(arguments.root).as_posix())
    print(
        "next: the toolchain's patterns, the profile's components, the fixtures' sources and CI, the page's "
        "sections, then the snapshots"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

__all__ = ["main", "scaffold"]
