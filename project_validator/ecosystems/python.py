"""Python: packaged with pyproject.toml or setup.py, judged by the interpreter versions CI runs."""

import re

from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis

PYTHON_PACKAGING = BuildSystem(
    name="Python packaging", files=("pyproject.toml", "setup.py"), languages=frozenset({"Python"})
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
    axis=versions_axis("Python version", "Python"),
)
