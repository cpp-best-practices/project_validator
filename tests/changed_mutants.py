"""The mutmut mutants of the functions a diff touches, for the repository's own mutation testing job.

    python tests/changed_mutants.py origin/main...HEAD

prints one mutant name pattern per line, for `mutmut run`. mutmut 3 names a mutant `<module>.x_<function>__mutmut_N`,
or `<module>.xǁ<Class>ǁ<method>__mutmut_N` for a method, and it only mutates top-level functions and the methods of
top-level classes, so a changed line selects the one of those it lies in (a nested function counts as the function
holding it). The pattern is `<module>.x_<function>*`: mutmut matches it against the mutants and, to choose the tests
of its clean pass, against the bare function name, which `__mutmut_*` would miss; a function whose name extends
another's (`x_top*` also matches `x_topology`) is then mutated too, which costs time but no correctness.

Nothing is selected for lines outside any function (a module constant, a class attribute), the methods of nested
classes, deleted files, and the functions mutmut leaves alone: decorated ones (except a bare `@staticmethod` or
`@classmethod`), `__getattribute__`, `__setattr__` and `__new__`, and an Enum's `__init__`.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

PACKAGE = "project_validator"
_FILE = re.compile(r"^\+\+\+ b/(.*?)\t?$", re.MULTILINE)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
_NEVER_MUTATED = frozenset({"__getattribute__", "__setattr__", "__new__"})
_NEVER_MUTATED_IN_ENUM = frozenset({"__init__", "_generate_next_value_"})
_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
_ALLOWED_DECORATORS = frozenset({"staticmethod", "classmethod"})

type Function = ast.FunctionDef | ast.AsyncFunctionDef


def changed_lines(diff: str) -> dict[str, set[int]]:
    """The line numbers, in the new file, that each file's hunks touch; a pure deletion touches the lines around it."""
    lines: dict[str, set[int]] = {}
    sections = re.split(r"^(?=diff --git )", diff, flags=re.MULTILINE)
    for section in sections:
        file = _FILE.search(section)
        if file is None:
            continue
        touched = lines.setdefault(file.group(1), set())
        for hunk in _HUNK.finditer(section):
            start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
            touched.update(range(start, start + count) if count else (max(start, 1), start + 1))
    return lines


def _mutated(function: Function, enum: bool) -> bool:
    """Whether mutmut mutates the function: not a decorated one (a bare @staticmethod or @classmethod aside), nor
    the few special methods it leaves alone."""
    if function.name in _NEVER_MUTATED or (enum and function.name in _NEVER_MUTATED_IN_ENUM):
        return False
    if not function.decorator_list:
        return True
    if len(function.decorator_list) != 1:
        return False
    decorator = function.decorator_list[0]
    return isinstance(decorator, ast.Name) and decorator.id in _ALLOWED_DECORATORS


def _is_enum(node: ast.ClassDef) -> bool:
    names = {base.id for base in node.bases if isinstance(base, ast.Name)}
    names |= {base.attr for base in node.bases if isinstance(base, ast.Attribute)}
    return bool(names & _ENUM_BASES)


def _span(function: Function, class_name: str | None) -> tuple[int, int, str]:
    first = min([function.lineno, *(decorator.lineno for decorator in function.decorator_list)])
    name = f"xǁ{class_name}ǁ{function.name}" if class_name else f"x_{function.name}"
    return first, function.end_lineno or function.lineno, name


def _spans(tree: ast.Module) -> list[tuple[int, int, str]]:
    """(first line, last line, mangled name) of every function mutmut mutates: top-level ones and the methods of
    top-level classes, each from its first decorator."""
    spans = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _mutated(node, enum=False):
            spans.append(_span(node, None))
        elif isinstance(node, ast.ClassDef):
            enum = _is_enum(node)
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and _mutated(child, enum):
                    spans.append(_span(child, node.name))
    return spans


def _module(path: str) -> str:
    module = path.removesuffix(".py").replace("/", ".")
    return module.removesuffix(".__init__")


def mutant_patterns(path: str, source: str, lines: Iterable[int]) -> list[str]:
    """The patterns selecting the mutants of the functions in `source` (at `path`) that `lines` fall in, sorted."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    spans = _spans(tree)
    module = _module(path)
    names = {name for line in lines for first, last, name in spans if first <= line <= last}
    return sorted(f"{module}.{name}*" for name in names)


def patterns_for(diff: str, read: Callable[[str], str | None]) -> list[str]:
    """The patterns for every changed Python file of the package that `read` can still find."""
    patterns: set[str] = set()
    for path, lines in changed_lines(diff).items():
        if not (path.startswith(f"{PACKAGE}/") and path.endswith(".py")):
            continue
        source = read(path)
        if source is not None:
            patterns.update(mutant_patterns(path, source, lines))
    return sorted(patterns)


def _git(*arguments: str, root: Path | None = None) -> str:
    """git's output, as text, whatever the user's diff and quoting settings, run at `root` (default: here)."""
    where = ["-C", str(root)] if root else []
    return subprocess.run(  # noqa: S603 - argv list, no shell
        ["git", *where, "-c", "core.quotePath=false", *arguments],  # noqa: S607 - git from PATH, as the suite does
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def git_diff(revisions: str, root: Path) -> str:
    """The diff of `revisions` in the repository at `root`, without context lines, so that every hunk line is a
    changed one."""
    options = ("--no-color", "--no-ext-diff", "--no-textconv", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/")
    return _git("diff", "-U0", *options, revisions, "--", f"{PACKAGE}/*.py", f"{PACKAGE}/**/*.py", root=root)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} REVISIONS", file=sys.stderr)
        return 2
    try:
        root = Path(_git("rev-parse", "--show-toplevel").strip())
        diff = git_diff(argv[1], root)
    except subprocess.CalledProcessError as error:
        sys.stderr.write(error.stderr)
        return error.returncode

    def read(path: str) -> str | None:
        file = root / path
        return file.read_text(encoding="utf-8") if file.is_file() else None

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # the method patterns hold a ǁ, whatever the locale
    for pattern in patterns_for(diff, read):
        print(pattern)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
