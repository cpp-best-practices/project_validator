"""What a project turns off in its tools (upstream #295): the diagnostics their configuration disables (`Disabled`), and
the suppressions written in the code (`Suppressions`, counted per file and tool). The score weighs a tool's strength
by them; nothing here judges.

A disabled diagnostic is `BLANKET` (everything: clang-tidy's `-*` with nothing enabled after it, ruff's `ALL`,
pylint's `all`, mypy's `ignore_errors`), `KEY` (a diagnostic that finds bugs: clang-tidy's `bugprone-*`, a compiler's
`-Wconversion`, ruff's bugbear `B` and bandit `S` codes, mypy's error codes, clippy's correctness lints) or `STYLISTIC`
(any other: one not known to find bugs weighs as style). Its scope is `GLOBAL` (the whole configuration) or `FILE`
(per-file ignores). It is justified when its line, or the line above it, carries a comment: any reason text, or a
link. An inline suppression is justified likewise by any text or link after it (`# noqa: E501 - a long URL`)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache

from project_validator import policy_tables
from project_validator.components import known
from project_validator.core import Project
from project_validator.facts import Command, Fact, Facts, Origin, Setting

BLANKET, KEY, STYLISTIC = "blanket", "key", "stylistic"
GLOBAL, FILE = "global", "file"


@dataclass(frozen=True, slots=True, kw_only=True)
class Disabled(Fact):
    """A diagnostic the configuration of `tool` turns off (see the module)."""

    tool: str
    diagnostic: str
    kind: str
    scope: str = GLOBAL
    justified: bool = False
    why: str = ""  # what the diagnostic guards against, where the validator says so


@dataclass(frozen=True, slots=True, kw_only=True)
class Suppressions(Fact):
    """The suppressions of `tool`'s diagnostics written in one file: how many, how many say why, and whether one turns
    off every diagnostic of the file (`# mypy: ignore-errors`, `/* eslint-disable */`, `#![allow(warnings)]`)."""

    tool: str
    count: int
    justified: int = 0
    blanket: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostics:
    """Which of a tool's diagnostics turn everything off (`blanket`) and which find bugs (`key`, globs), and what some
    of them guard against (`reasons`: glob, why), as `policy/diagnostics.toml` says (upstream #440)."""

    blanket: tuple[str, ...] = ()
    key: tuple[str, ...] = ()
    reasons: tuple[tuple[str, str], ...] = ()

    def why(self, diagnostic: str) -> str:
        return next((why for glob, why in self.reasons if fnmatchcase(diagnostic, glob)), "")

    def kind(self, diagnostic: str) -> str:
        if diagnostic in self.blanket:
            return BLANKET
        found = any(fnmatchcase(diagnostic, glob) for glob in self.key) or bool(self.why(diagnostic))
        return KEY if found else STYLISTIC


@cache
def diagnostics(tool: str) -> Diagnostics:
    """What `policy/diagnostics.toml` says of `tool`'s diagnostics: a table may take its key diagnostics from another
    tool's (`key_of`); a tool it doesn't name has only stylistic ones."""
    table = policy_tables.load("diagnostics")
    entry = table.get(tool, {})
    return Diagnostics(
        blanket=tuple(entry.get("blanket", ())),
        key=tuple(table[entry["key_of"]]["key"] if "key_of" in entry else entry.get("key", ())),
        reasons=tuple((reason["glob"], reason["why"]) for reason in entry.get("reasons", ())),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Disabler:
    """How the settings of `settings` (a reader's name) turn off diagnostics of `tool`: `disabled` gives each
    (diagnostic, scope) a setting turns off. Which of them turn everything off or find bugs is policy
    (`diagnostics`)."""

    tool: str
    settings: str
    disabled: Callable[[Setting], Iterable[tuple[str, str]]]

    def why(self, diagnostic: str) -> str:
        return diagnostics(self.tool).why(diagnostic)

    def kind(self, diagnostic: str) -> str:
        return diagnostics(self.tool).kind(diagnostic)


@dataclass(frozen=True, slots=True, kw_only=True)
class Marker:
    """An inline suppression of `tool`'s diagnostics in sources of `languages`: `pattern` finds one, its `codes`
    group the diagnostics it names (none: every one), and the text after it says why; `blanket` finds one that turns
    off a whole file."""

    tool: str
    languages: frozenset[str]
    pattern: re.Pattern[str]
    blanket: re.Pattern[str] | None = None


def listed(value: object) -> tuple[str, ...]:
    """A setting's diagnostics: a list, or a comma-separated string."""
    if isinstance(value, tuple | list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(part.strip() for part in str(value).replace("\n", ",").split(",") if part.strip())


def keyed(*keys: str, per_file: tuple[str, ...] = ()) -> Callable[[Setting], Iterator[tuple[str, str]]]:
    """The diagnostics listed under `keys` (globally) and under the tables `per_file` (per-file ignores, keyed
    `<table>.<glob>`)."""

    def disabled(setting: Setting) -> Iterator[tuple[str, str]]:
        if setting.key in keys:
            yield from ((code, GLOBAL) for code in listed(setting.value))
        elif any(setting.key.startswith(f"{table}.") for table in per_file):
            yield from ((code, FILE) for code in listed(setting.value))
        elif setting.key in per_file:  # flake8's per-file-ignores: `path: codes` lines
            for line in str(setting.value).splitlines():
                _, colon, codes = line.partition(":")
                yield from ((code, FILE) for code in listed(codes) if colon)

    return disabled


# A comment's text: after `#`, `//` or `;`.
_COMMENT = re.compile(r"(?:#|//|;)\s*(?P<text>.*)$")
_REASON = re.compile(r"\w{2,}|https?://")


# A glob of diagnostics a comment may name for several (`cppcoreguidelines-pro-bounds-*`).
_GLOB = re.compile(r"(?<![\w*-])[\w.-]*\*[\w.*-]*")


def _named(line: str, diagnostic: str) -> str | None:
    """How `line` names `diagnostic`: as itself, or by a glob that covers it; None where it does not."""
    if re.search(rf"(?<!\w){re.escape(diagnostic)}(?![\w-])", line):
        return diagnostic
    return next((glob for glob in _GLOB.findall(line) if glob != "*" and fnmatchcase(diagnostic, glob)), None)


def _justified(text: str, diagnostic: str) -> bool:
    """Whether the configuration says why it turns `diagnostic` off: a comment on a line naming it (or a glob that
    covers it), or on the line above."""
    lines = text.splitlines()
    for number, line in enumerate(lines):
        if (name := _named(line, diagnostic)) is None:
            continue
        here = _COMMENT.search(line.split(name, 1)[1])
        above = _COMMENT.match(lines[number - 1].strip()) if number else None
        if any(found and _REASON.search(found["text"].replace(name, "")) for found in (here, above)):
            return True
    return False


def disabled_facts(project: Project, facts: Facts, disablers: Iterable[Disabler]) -> Iterator[Disabled]:
    """Each diagnostic the tools' settings turn off, kind and scope, and whether a comment says why."""
    texts: dict[str, str] = {}
    for disabler in disablers:
        for setting in facts.where(Setting, tool=disabler.settings):
            for diagnostic, scope in disabler.disabled(setting):
                if setting.path not in texts:
                    texts[setting.path] = project.read_text(setting.path) if project.exists(setting.path) else ""
                yield Disabled(
                    origin=setting.origin,
                    tool=disabler.tool,
                    diagnostic=diagnostic,
                    kind=disabler.kind(diagnostic),
                    scope=scope,
                    justified=_justified(texts[setting.path], diagnostic),
                    why=disabler.why(diagnostic),
                )


# A compiler's warnings turned off on a command line: every one (`-w`, MSVC's `/W0`), or one (`-Wno-conversion`,
# `-Wno-error=shadow`, MSVC's `/wd4244`).
_COMPILER_OFF = re.compile(r"^(?:-w|/w|/W0|-Wno-(?:error=)?(?P<gnu>[\w=+-]+)|/wd(?P<msvc>\d+))$")
# The C and C++ compilers' programs, whose command lines say which warnings they turn off.
COMPILERS = re.compile(
    r"^(?:.*/)?(?:gcc|g\+\+|cc|c\+\+|clang|clang\+\+|clang-cl|cl|icc|icpc|icx|icpx|nvcc|emcc|em\+\+)"
    r"(?:-\d+(?:\.\d+)*)?(?:\.exe)?$",
    re.IGNORECASE,
)


def compiler_disabled(commands: Iterable[Command]) -> Iterator[Disabled]:
    """The compiler warnings CI's compiler command lines turn off, every one (`-w`) or each (`-Wno-shadow`): `-w`
    means something else to other programs (`grep -w`, Go's `-ldflags "-s -w"`)."""
    for command in commands:
        if not command.argv or not COMPILERS.match(command.argv[0]):
            continue
        for word in command.argv[1:]:
            found = _COMPILER_OFF.match(word)
            if found is None:
                continue
            name = found["gnu"] or found["msvc"] or "*"
            yield Disabled(
                origin=command.origin, tool="compiler", diagnostic=word, kind=diagnostics("compiler").kind(name)
            )


def _counted(text: str, marker: Marker) -> tuple[int, int, bool]:
    count = justified = 0
    for found in marker.pattern.finditer(text):
        count += 1
        justified += bool(_REASON.search(found["reason"] or ""))
    blanket = marker.blanket is not None and marker.blanket.search(text) is not None
    return count, justified, blanket


def suppression_facts(project: Project, facts: Facts, markers: Iterable[Marker]) -> Iterator[Suppressions]:
    """The suppressions written in each of the product's source files, counted per tool."""
    from project_validator.facts.structure import SourceFile  # structure reads the profiles, which define markers

    markers = tuple(markers)
    for source in facts.of(SourceFile):
        found = [marker for marker in markers if source.language in marker.languages]
        if not found or source.role != "product" or not source.lines:
            continue
        text = project.read_text(source.path)
        for marker in found:
            count, justified, blanket = _counted(text, marker)
            if count or blanket:
                yield Suppressions(
                    origin=Origin(path=source.path), tool=marker.tool, count=count, justified=justified, blanket=blanket
                )


def known_disablers() -> tuple[Disabler, ...]:
    return known(Disabler)


def known_markers() -> tuple[Marker, ...]:
    return known(Marker)


def suppressions(project: Project, facts: Facts) -> Iterator[Fact]:
    """Every `Disabled` and `Suppressions` fact of the project."""
    yield from disabled_facts(project, facts, known_disablers())
    yield from compiler_disabled(facts.of(Command))
    yield from suppression_facts(project, facts, known_markers())


__all__ = [
    "BLANKET",
    "FILE",
    "GLOBAL",
    "KEY",
    "STYLISTIC",
    "Diagnostics",
    "Disabled",
    "Disabler",
    "Marker",
    "Suppressions",
    "compiler_disabled",
    "diagnostics",
    "keyed",
    "known_disablers",
    "known_markers",
    "listed",
    "suppressions",
]
