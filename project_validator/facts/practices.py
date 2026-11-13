"""Practices that ask for settings: the strict warning set (`compiler-warnings`) and warnings that fail the build
(`warnings-as-errors`).

A `Practice`, a component of the profile that knows the language, lists the `Requirement`s it asks for: all of them
(the warning set), or any one (warnings as errors). A requirement is met by a command CI runs (`runs`, matched in the
command as run, with the variables it is given), by the profile's settings files (a `requirement_reader` matches the
same pattern in them, heuristically, until they are read structurally), or by facts its `found` picks out: for C and
C++, the `CompilerOption`s that apply to the compiler being judged. A practice judged per compiler names the
`compilers` CI builds with.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from project_validator.components import known
from project_validator.facts import ActionStep, Command, Fact, Facts, Origin, Setting, resolved
from project_validator.facts.settings import SettingsReader
from project_validator.facts.tools import ToolRun
from project_validator.text import Pattern


class PracticeName(enum.StrEnum):
    """The practices that ask for settings, as the checks are called."""

    WARNINGS = "compiler-warnings"
    WARNINGS_AS_ERRORS = "warnings-as-errors"
    HARDENING = "hardening"
    EXTENSIONS = "cxx-extensions"
    SANITIZERS = "sanitizers"


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where a requirement is met, and what it needs that the build cannot decide (an option it is behind)."""

    where: str
    requires: frozenset[str] = frozenset()

    def __str__(self) -> str:
        return f"{self.where} (when {' and '.join(sorted(self.requires))})" if self.requires else self.where


type Found = Callable[[Facts, str | None], Iterable[Evidence]]


def _nothing(_facts: Facts, _compiler: str | None) -> Iterator[Evidence]:
    return iter(())


@dataclass(frozen=True, slots=True, kw_only=True)
class Requirement:
    """A setting a practice asks for, `name`d as messages give it: met by a CI command (or a reusable step, with its
    inputs) `runs` matches, by a run of one of its `tools`, by the settings files a `requirement_reader` matches
    `pattern` in (by default the same as `runs`), or by the facts `found` returns for a compiler (None: the language
    has no compilers to tell apart)."""

    name: str
    runs: re.Pattern[str] | None = None
    pattern: re.Pattern[str] | None = None
    found: Found = _nothing
    # Tools whose runs meet it (RuboCop, however CI runs it: directly, through a Rake task or an action).
    tools: tuple[str, ...] = ()
    # Text one of which a command `runs` matches holds: the commands without any are not searched.
    hints: tuple[str, ...] = ()

    @property
    def in_files(self) -> re.Pattern[str] | None:
        return self.pattern or self.runs


def required(pattern: Pattern, *, in_files: bool = True, tools: tuple[str, ...] = ()) -> Requirement:
    """A requirement a named pattern recognises in CI commands and (unless not `in_files`) in settings files, or that
    a run of one of `tools` meets."""
    return Requirement(name=pattern.name, runs=pattern.regex, pattern=None if in_files else _NEVER, tools=tools)


_NEVER = re.compile(r"(?!)")


def always(*requirements: Requirement) -> Callable[[Facts, str | None], tuple[Requirement, ...]]:
    """Requirements that do not depend on the project."""
    return lambda _facts, _compiler: requirements


_ASSIGNMENT = re.compile(r"^(?:-D)?[\w:]+=(?P<value>.+)$")


def command_text(command: Command) -> str:
    """A command as run, with the variables it is given (`RUSTFLAGS=-D warnings cargo build`), and the values it
    assigns standing on their own (`-DCMAKE_CXX_FLAGS=-Werror` sets `-Werror`)."""
    words = (*(f"{name}={value}" for name, value in command.env.items()), *resolved(command))
    values = (match["value"] for word in words if (match := _ASSIGNMENT.match(word)))
    return " ".join((*words, *values))


def requirement_reader(name: str, files: tuple[str, ...], requirements: Iterable[Requirement]) -> SettingsReader:
    """A reader of the settings `files` that records each requirement whose pattern it matches, as a `Setting` of the
    tool `name` keyed by the requirement's name; heuristic, as the files are not parsed."""
    patterns = [
        (requirement.name, found)
        for requirement in requirements
        if (found := requirement.in_files) and found is not _NEVER
    ]

    def read(path: str, text: str) -> Iterator[Fact]:
        for key, pattern in patterns:
            if pattern.search(text):
                yield Setting(origin=Origin(path=path), tool=name, key=key, value=True, heuristic=True)

    return SettingsReader(name=name, files=files, read=read)


@dataclass(frozen=True, slots=True, kw_only=True)
class Wording:
    """How a practice's findings are worded, for the policy: what the profile knows about the language that the
    policy's sentences need. `kind` names the requirements ("compiler warning flags"; listed joined by `separator`),
    `hint` says how to meet them, and `searched` where they are looked for. The rest replaces a policy sentence where
    it would not fit the practice: `passed` (with `{found}`, the requirements met) and `failed` (met in nothing),
    `question` (what an unknown answer leaves open), and the `preferred` requirements of a practice met by any one,
    with the `preference` advice when only others are met."""

    kind: str
    hint: str = ""
    searched: str = "CI configuration"
    separator: str = ", "
    passed: str = ""
    failed: str = ""
    question: str = ""
    preferred: tuple[str, ...] = ()
    preference: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Practice:
    """What a practice (`WARNINGS`, `WARNINGS_AS_ERRORS`) asks of `languages`: `requirements` (which may depend on
    the facts: C# asks for other settings than F#), all of them or, with `any_one`, one. The settings the readers it
    `reads` record under a requirement's name meet it (see `requirement_reader`), and their unknowns may hide it. A
    practice judged per compiler names the `compilers` CI builds with. A practice that `forbids` its requirements is
    met when none of them is found. How its findings are worded is `words`, apart from what it asks."""

    name: str
    languages: frozenset[str]
    requirements: Callable[[Facts, str | None], Sequence[Requirement]]
    words: Wording
    any_one: bool = False
    reads: tuple[str, ...] = ()
    compilers: Callable[[Facts], Sequence[str]] | None = None
    # Settings that must not be found (`-Ounchecked`), rather than settings that must.
    forbids: bool = False
    # Why the practice does not apply to the project (a Go library builds no binary to harden); None when it does.
    skipped: Callable[[Facts], str | None] = lambda _facts: None


def known_practices() -> tuple[Practice, ...]:
    """Every practice defined by a module of the shared build systems, the shared tools or a profile."""
    return known(Practice)


def practices_of(name: str, language: str) -> tuple[Practice, ...]:
    return tuple(practice for practice in known_practices() if practice.name == name and language in practice.languages)


@dataclass(frozen=True, slots=True)
class Texts:
    """Every CI command and reusable step, with its text as requirements are matched in it; what each pattern
    matches is kept, as practices judged per language and per compiler ask for the same requirements again."""

    found: tuple[tuple[Fact, str], ...]
    matched: dict[tuple[str, int, tuple[str, ...]], tuple[Fact, ...]] = field(default_factory=dict)

    def matching(self, pattern: re.Pattern[str], hints: tuple[str, ...] = ()) -> tuple[Fact, ...]:
        """The commands and steps whose text `pattern` matches (those holding none of `hints` are not searched)."""
        key = (pattern.pattern, pattern.flags, hints)
        if key not in self.matched:
            searched = ((fact, text) for fact, text in self.found if not hints or any(hint in text for hint in hints))
            self.matched[key] = tuple(fact for fact, text in searched if pattern.search(text))
        return self.matched[key]


def ci_texts(facts: Facts) -> Texts:
    """The texts requirements are matched in: every command (see `command_text`) and reusable step; made once for
    the facts."""
    return facts.shared(
        "ci texts",
        lambda: Texts((*((command, command_text(command)) for command in facts.of(Command)), *_steps(facts))),
    )


def met(
    practice: Practice, requirement: Requirement, facts: Facts, compiler: str | None, texts: Texts | None = None
) -> tuple[Evidence, ...]:
    """Where a requirement is met: the CI commands and steps it `runs` matches (`texts`, by default all of them), the
    runs of its tools, the settings files the practice's readers matched it in, and the facts its `found` picks out."""
    searched = ci_texts(facts) if texts is None else texts
    matched = searched.matching(requirement.runs, requirement.hints) if requirement.runs is not None else ()
    commands = (Evidence(f"CI ({fact.origin.path})") for fact in matched)
    runs = (Evidence(f"CI ({run.origin.path})") for run in facts.of(ToolRun) if run.tool in requirement.tools)
    settings = (
        Evidence(setting.path)
        for setting in facts.of(Setting)
        if setting.tool in practice.reads and setting.key == requirement.name
    )
    return tuple(dict.fromkeys((*commands, *runs, *settings, *requirement.found(facts, compiler))))


def named(facts: Facts, patterns: Iterable[Pattern]) -> list[str]:
    """The names of the `patterns` a CI command or reusable step, or a pre-commit hook, matches, in order: a tool that
    either runs is run."""
    hooks = (str(setting.value) for setting in facts.where(Setting, tool="pre-commit", key="hook"))
    texts = (*(text for _, text in ci_texts(facts).found), *hooks)
    return list(dict.fromkeys(pattern.name for pattern in patterns for text in texts if pattern.regex.search(text)))


def _steps(facts: Facts) -> Iterator[tuple[ActionStep, str]]:
    """Each reusable step CI uses, as `uses: owner/repo@ref` and its inputs (`ini-values: error_reporting=E_ALL`)."""
    for step in facts.of(ActionStep):
        yield step, "\n".join((f"uses: {step.uses}", *(f"{name}: {value}" for name, value in step.inputs.items())))


def handled(name: str) -> Callable[[], frozenset[str]]:
    """The languages some practice called `name` asks something of."""
    return lambda: frozenset().union(*(practice.languages for practice in known_practices() if practice.name == name))


__all__ = [
    "Evidence",
    "Practice",
    "PracticeName",
    "Requirement",
    "Wording",
    "always",
    "ci_texts",
    "command_text",
    "handled",
    "known_practices",
    "met",
    "named",
    "practices_of",
    "required",
    "requirement_reader",
]
