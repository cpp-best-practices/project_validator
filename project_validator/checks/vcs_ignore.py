import enum
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from project_validator.core import Context, Result, check
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST, check_each_ecosystem, languages_of


class Syntax(enum.Enum):
    GLOB = enum.auto()
    REGEX = enum.auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    """An ignore rule: `written` as it appears in its file, and the `pattern` it ignores in its `syntax`.

    A rooted glob `pattern` starts with "/", as in a .gitignore.
    """

    written: str
    pattern: str
    syntax: Syntax


def _glob(written: str, pattern: str | None = None) -> Entry:
    return Entry(written=written, pattern=written if pattern is None else pattern, syntax=Syntax.GLOB)


def _rooted_glob(written: str, pattern: str) -> Entry:
    return _glob(written, "/" + pattern.lstrip("/"))


def _regex(written: str, pattern: str) -> Entry:
    return Entry(written=written, pattern=pattern, syntax=Syntax.REGEX)


def _rule_lines(text: str) -> Iterator[str]:
    """The stripped lines of an ignore file; blank lines and comments ignore nothing."""
    lines = (line.strip() for line in text.splitlines())
    return (line for line in lines if line and not line.startswith("#"))


def _git_entries(text: str) -> tuple[Entry, ...]:
    """Negations re-include what earlier entries ignored, so they ignore nothing."""
    return tuple(_glob(line) for line in _rule_lines(text) if not line.startswith("!"))


MERCURIAL_SYNTAXES: dict[str, Callable[[str, str], Entry]] = {
    "re": _regex,
    "regexp": _regex,
    "relre": _regex,
    "glob": _glob,
    "relglob": _glob,
    "rootglob": _rooted_glob,
    "path": _rooted_glob,
    "relpath": _rooted_glob,
}

MERCURIAL_UNFOLLOWED = frozenset({"include", "subinclude", "listfile", "listfile0", "rootfilesin", "set"})

MERCURIAL_SYNTAX_LINE = re.compile(r"syntax:\s*(?P<syntax>\S+)")


def _mercurial_entry(line: str, syntax: str) -> Entry | None:
    """An entry in the current `syntax`, unless a prefix (e.g. glob:) names its own; includes are not followed."""
    prefix, separator, pattern = line.partition(":")
    if separator and prefix in MERCURIAL_SYNTAXES:
        return MERCURIAL_SYNTAXES[prefix](line, pattern)
    if separator and prefix in MERCURIAL_UNFOLLOWED:
        return None
    entry = MERCURIAL_SYNTAXES.get(syntax)
    return None if entry is None else entry(line, line)


def _mercurial_entries(text: str) -> tuple[Entry, ...]:
    """A .hgignore holds regular expressions until a `syntax:` line switches the syntax of the lines that follow."""
    syntax = "regexp"
    entries: list[Entry] = []
    for line in _rule_lines(text):
        if switch := MERCURIAL_SYNTAX_LINE.fullmatch(line):
            syntax = switch["syntax"]
        elif entry := _mercurial_entry(line, syntax):
            entries.append(entry)
    return tuple(entries)


def _bazaar_entry(line: str) -> Entry | None:
    """RE: marks a regular expression, ./ roots a glob, !! forces an ignore and a single ! is an exception."""
    rule = line.removeprefix("!!")
    if rule.startswith("!"):
        return None
    if rule[:3].upper() == "RE:":
        return _regex(line, rule[3:])
    if rule.startswith("./"):
        return _rooted_glob(line, rule[2:])
    return _glob(line, rule)


def _bazaar_entries(text: str) -> tuple[Entry, ...]:
    return tuple(entry for line in _rule_lines(text) if (entry := _bazaar_entry(line)))


FOSSIL_GLOB_SEPARATORS = re.compile(r"[\s,]+")


def _fossil_entries(text: str) -> tuple[Entry, ...]:
    """Fossil globs are separated by commas or whitespace and may be quoted."""
    globs = (glob.strip("'\"") for glob in FOSSIL_GLOB_SEPARATORS.split(text))
    return tuple(_glob(glob) for glob in globs if glob)


@dataclass(frozen=True, slots=True, kw_only=True)
class IgnoreFile:
    """A file in which a version control system lists what it must not track, and how to read its entries."""

    path: str
    entries: Callable[[str], tuple[Entry, ...]]


# Jujutsu reads .gitignore too; Subversion keeps its ignores in svn:ignore properties, which are not files.
IGNORE_FILES = (
    IgnoreFile(path=".gitignore", entries=_git_entries),
    IgnoreFile(path=".hgignore", entries=_mercurial_entries),
    IgnoreFile(path=".bzrignore", entries=_bazaar_entries),
    IgnoreFile(path=".fossil-settings/ignore-glob", entries=_fossil_entries),
)


def _ignored_at_top_level(names: str) -> re.Pattern[str]:
    """Globs that ignore one of `names` at the top of the repository, as a directory or with all of its contents."""
    return re.compile(rf"(?:\*\*/|/)?(?:{names})(?:/\**)?", re.IGNORECASE)


def _directories(*names: str) -> tuple[str, ...]:
    """The paths of `names` as an ignore rule sees them: the directory itself and what is inside it."""
    return tuple(path for name in names for path in (name, f"{name}/"))


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildOutputs:
    """The build outputs of an ecosystem that must never be committed, and the ignore entries that ignore them.

    A glob entry ignores the outputs when it is one of `globs`; a regular expression when it matches one of `paths`.
    """

    name: str
    globs: re.Pattern[str]
    paths: tuple[str, ...]
    hint: str


BUILD_OUTPUTS = {
    C_AND_CXX: BuildOutputs(
        name="the build directory",
        globs=_ignored_at_top_level(r"(?:\[Bb\]uild|_?build|out|cmake-build)(?:[-_*][\w*-]*)?"),
        paths=_directories("build", "out", "_build", "cmake-build-debug"),
        hint="consider ignoring the build directory (e.g. build/ and out/)",
    ),
    PYTHON: BuildOutputs(
        name="Python bytecode",
        globs=_ignored_at_top_level(r"__pycache__|\*\.py(?:c|\[[cod]+\])"),
        paths=(*_directories("__pycache__"), "module.pyc"),
        hint="consider ignoring __pycache__/ and *.py[cod]",
    ),
    RUST: BuildOutputs(
        name="the target directory",
        globs=_ignored_at_top_level("target"),
        paths=_directories("target"),
        hint="consider ignoring /target",
    ),
}


def _regex_matches_any(pattern: str, paths: tuple[str, ...]) -> bool:
    try:
        compiled = re.compile(pattern)
    except re.error:
        return False
    return any(compiled.search(path) for path in paths)


def _ignores(entry: Entry, outputs: BuildOutputs) -> bool:
    if entry.syntax is Syntax.REGEX:
        return _regex_matches_any(entry.pattern, outputs.paths)
    return outputs.globs.fullmatch(entry.pattern) is not None


def _ignoring_entry(ignore_file: IgnoreFile, outputs: BuildOutputs, context: Context) -> Entry | None:
    entries = ignore_file.entries(context.project.read_text(ignore_file.path))
    return next((entry for entry in entries if _ignores(entry, outputs)), None)


def _present_ignore_files(context: Context) -> tuple[IgnoreFile, ...]:
    return tuple(ignore_file for ignore_file in IGNORE_FILES if context.project.exists(ignore_file.path))


def _outputs_ignored(outputs: BuildOutputs, context: Context) -> Result:
    """Every version control system the project is set up for must ignore the outputs."""
    found = {
        ignore_file.path: _ignoring_entry(ignore_file, outputs, context)
        for ignore_file in _present_ignore_files(context)
    }
    unignored = tuple(path for path, entry in found.items() if entry is None)
    if unignored:
        verb = "does" if len(unignored) == 1 else "do"
        return Result.warned(f"{', '.join(unignored)} {verb} not ignore {outputs.name}", outputs.hint)
    return Result.passed("; ".join(f"{path} ignores {entry.written}" for path, entry in found.items() if entry))


IGNORE_FILE_NAMES = ", ".join(ignore_file.path for ignore_file in IGNORE_FILES)


@check(
    name="vcs-ignore",
    description="A .gitignore (or .hgignore, .bzrignore, ...) keeps build outputs (e.g. build/, __pycache__/, target/) "
    "out of version control",
    languages=languages_of(BUILD_OUTPUTS),
)
def vcs_ignore(context: Context) -> Result:
    if not _present_ignore_files(context):
        return Result.failed(
            f"no version control ignore file found ({IGNORE_FILE_NAMES}); build outputs can be committed by accident",
            "consider adding a .gitignore (or your version control system's equivalent) that ignores build outputs",
        )
    return check_each_ecosystem(context, BUILD_OUTPUTS, _outputs_ignored)
