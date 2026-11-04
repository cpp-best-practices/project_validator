"""Python: packaged with pyproject.toml or setup.py, judged by the interpreter versions CI runs."""

import re

from project_validator.core import Context
from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.evidence import first_existing
from project_validator.rules import Formatter
from project_validator.text import pattern

PYTHON_PACKAGING = BuildSystem(
    name="Python packaging", files=("pyproject.toml", "setup.py"), languages=frozenset({"Python"})
)

PYTHON_FORMATTER_SECTIONS = re.compile(r"^\s*\[tool\.(?:ruff|black)\b", re.MULTILINE)


def _python_formatter_file(context: Context) -> str | None:
    project = context.project
    if project.exists("pyproject.toml") and PYTHON_FORMATTER_SECTIONS.search(project.read_text("pyproject.toml")):
        return "pyproject.toml"
    return first_existing(context, ("ruff.toml", ".ruff.toml"))


RUFF_OR_BLACK = Formatter(
    name="ruff format or black",
    config_file=_python_formatter_file,
    runs=(
        pattern("ruff format", r"\bruff\s+format\b"),
        pattern("black", r"(?<![\w.-])black\b[^\n]*\s--(?:check|diff)\b|\bpsf/black@"),
    ),
    hint="consider a CI job that runs ruff format --check (or black --check)",
    default_style=True,
)

PYTHON = Ecosystem(
    label="Python",
    languages=frozenset({"Python"}),
    build_systems=(PYTHON_PACKAGING,),
    source_suffixes={".py": "Python"},
    toolchain=ToolchainPatterns(
        language="Python",
        versions=(
            re.compile(r"\bpython-version\W+(\d+(?:\.(?:\d+|x))*|pypy[\d.]*)"),
            re.compile(r"\bpython:(\d+(?:\.\d+)*)"),
            re.compile(r"\bpython(\d\.\d+)\b"),
        ),
        usage=re.compile(
            r"\bpython[\d.]*\s+(?:-|\S+\.py\b)|\bpip\d*\s+install\b|\bpytest\b|\btox\b|\bnox\b|\bsetup-python\b"
        ),
    ),
    rules=(versions_axis("Python version", "Python"), RUFF_OR_BLACK),
)
