"""The simple commands of the shell scripts CI runs, derived from their syntax tree (`facts.shell_syntax`).

A command substitution's commands (`$(…)`, backquotes) come before the command they are part of, marked `nested`;
leading `NAME=value` assignments (and arrays, `NAME=(a b)`) are the command's environment; a conditional expression,
`[[ … ]]`, an arithmetic command and the headers of compound commands run nothing, and the body of a here-document is
data. Each command keeps what decides whether its failure fails the script (see `exit_status`): the operator after it,
the condition it is part of, the fallback after its `||`, and whether the command after it reads its exit status.
`split_words`, `command_line` and `quoted` are the one place an embedded command line is split or joined.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace

from project_validator.facts.shell_syntax import (
    Assignment,
    Case,
    Compounded,
    For,
    Function,
    Group,
    If,
    Item,
    Loop,
    Pipeline,
    Script,
    ShellSyntaxError,
    Simple,
    Subshell,
    Test,
    Word,
    parse,
)
from project_validator.parsing import Span


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellCommand:
    """A simple command, with what decides whether its failure fails the script (see `exit_status`)."""

    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    line: str
    # The operator after it on its line (`|`, `|&`, `&&`, `||`, `;`, `&`), or "" at the line's end.
    operator: str = ""
    # The keyword whose condition it is part of (`if`, `elif`, `while`, `until`), or `!`, which negates it.
    condition: str = ""
    # After `||`: the command that runs in its place when it fails and that can succeed, as written; "" when what
    # follows `||` fails again (`exit 1`), or goes on past the line, where it is not read.
    fallback: str = ""
    # Whether the command after it reads its exit status (`$?`, `PIPESTATUS`).
    checked: bool = False
    # Whether it runs in a command substitution, whose status is the business of the command around it.
    nested: bool = False
    # Where it is in the script; it does not change what the command is.
    span: Span | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Unsplittable:
    """What is wrong in a script (an unclosed quote, an `if` without its `fi`): the line it is on, why, and where in the
    script (`span`). The commands around it, and in it as far as they can be read, are still split."""

    line: str
    reason: str
    span: Span | None = None


def split_words(text: str, *, comments: bool = False) -> tuple[str, ...]:
    """The words of one embedded command line (an action's `args` input, an alias), as a POSIX shell splits them, a
    `#` word and what follows it dropped when `comments` says so; `ShellSyntaxError` when they do not split."""
    try:
        return tuple(shlex.split(text, comments=comments))
    except ValueError as error:
        raise ShellSyntaxError(str(error)) from error


def command_line(argv: Iterable[str]) -> str:
    """`argv` as one command line, quoted so that `split_words` splits it back into the same words."""
    return shlex.join(argv)


def quoted(word: str) -> str:
    """`word` quoted for a POSIX shell, when it needs to be."""
    return shlex.quote(word)


# What reads the exit status of the command before.
READS_STATUS = re.compile(r"\$\?|\$\{\?\}|PIPESTATUS")
# The longest fallback named whole; a longer one is named by its program.
_FALLBACK_SHOWN = 24
_CONTINUATION = re.compile(r"\\\r?\n")
_POWERSHELL_CONTINUATION = re.compile(r"`\r?\n")
# PowerShell has no compound commands in the tree: its keywords and braces are words, read as they always were.
_KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}"})
_CLOSING = frozenset({"fi", "done", "esac"})
_CONDITIONS = frozenset({"if", "elif", "while", "until"})
_BODIES = frozenset({"then", "do"})


def _fails(argv: tuple[str, ...]) -> bool:
    """Whether a command fails whatever came before: `false`, or an `exit`/`return` other than `exit 0`."""
    return argv[:1] == ("false",) or (argv[:1] in (("exit",), ("return",)) and argv[1:2] != ("0",))


@dataclass(slots=True)
class _Found:
    """A simple command of one script, before the flags that need its neighbours are settled."""

    command: Simple
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    operator: str
    condition: str
    # After `||`: the pipelines that run when it fails, to the end of its and-or list.
    rest: tuple[Pipeline, ...] = ()
    checked: bool = False


@dataclass(slots=True)
class _Level:
    """The commands of one script (the whole, or a substitution's), as the tree is walked."""

    text: str
    root: Script
    powershell: bool
    found: list[_Found] = field(default_factory=list)
    substitutions: list[Word] = field(default_factory=list)  # the words that hold them, in order

    def line(self, offset: int) -> int:
        return self.root.line_of(offset)

    def line_text(self, index: int) -> str:
        start, end = self.root.lines[index]
        continuation = _POWERSHELL_CONTINUATION if self.powershell else _CONTINUATION
        return continuation.sub(" ", self.text[start:end]).strip()

    # walking the tree

    def script(self, script: Script, condition: str) -> None:
        for item in script.items:
            self.item(item, condition)

    def item(self, item: Item, condition: str) -> None:
        chain = item.list
        for index, pipeline in enumerate(chain.pipelines):
            after = chain.operators[index] if index < len(chain.operators) else item.terminator
            rest = chain.pipelines[index + 1 :] if after == "||" else ()
            self.pipeline(pipeline, after, rest, condition)

    def pipeline(self, pipeline: Pipeline, after: str, rest: tuple[Pipeline, ...], condition: str) -> None:
        for index, command in enumerate(pipeline.commands):
            last = index == len(pipeline.commands) - 1
            operator = after if last else pipeline.operators[index]
            negated = "!" if pipeline.negated and index == 0 else ""
            if isinstance(command, Simple):
                self.simple(command, operator, condition or negated, rest if last else ())
            else:
                self.compound(command, operator, condition or negated, rest if last else ())

    def simple(self, command: Simple, operator: str, condition: str, rest: tuple[Pipeline, ...]) -> None:
        self.substitutions.extend(_words_of(command))
        argv = tuple(word.value for word in command.words)
        if self.powershell:
            argv, condition = self.powershell_words(command, argv, condition)
        env = tuple((assignment.name, _assigned(assignment)) for assignment in command.assignments)
        if argv:
            self.found.append(_Found(command, argv, env, operator, condition, rest))

    def powershell_words(self, command: Simple, argv: tuple[str, ...], condition: str) -> tuple[tuple[str, ...], str]:
        """PowerShell's words as the line splitter always read them: leading keywords dropped (a condition's keyword
        kept for the commands up to `then`/`do` on its line), and a closing word dropping its command."""
        keywords = 0
        line = self.line(command.start)
        previous = self.found[-1] if self.found else None
        if previous is not None and self.line(previous.command.start) == line and previous.condition in _CONDITIONS:
            condition = condition or previous.condition
        while keywords < len(argv) and argv[keywords] in _KEYWORDS:
            keyword = argv[keywords]
            condition = keyword if keyword in _CONDITIONS else "" if keyword in _BODIES else condition
            keywords += 1
        argv = argv[keywords:]
        if argv[:1] in (("for",), ("select",)) or (argv and argv[0] in _CLOSING):
            return (), condition
        return _powershell_assigned(command.words[keywords:], argv), condition

    def compound(self, command: Compounded, operator: str, condition: str, rest: tuple[Pipeline, ...]) -> None:
        before = len(self.found)
        inner = command.command
        for redirection in command.redirections:
            if redirection.target is not None:
                self.substitutions.append(redirection.target)
        if isinstance(inner, (Subshell, Group)):
            self.script(inner.body, condition)
        elif isinstance(inner, If):
            self.branches(inner)
        elif isinstance(inner, Loop):
            self.script(inner.condition, inner.keyword)
            self.script(inner.body, "")
        else:
            self.other(inner)
        self.inherit(before, inner.end, operator, rest)

    def branches(self, command: If) -> None:
        for clause in command.clauses:
            self.script(clause.condition, clause.keyword)
            self.script(clause.body, "")
        if command.otherwise is not None:
            self.script(command.otherwise, "")

    def other(self, command: object) -> None:
        if isinstance(command, For):
            self.substitutions.extend(command.words or ())
            self.script(command.body, "")
        elif isinstance(command, Case):
            self.substitutions.extend([command.subject] if command.subject else [])
            for case_item in command.items:
                self.substitutions.extend(case_item.patterns)
                self.script(case_item.body, "")
        elif isinstance(command, Test):
            self.substitutions.extend(command.words)
        elif isinstance(command, Function):
            body = command.body
            self.compound(Compounded(body, ()), "", "", ()) if not isinstance(body, Simple) else self.simple(
                body, "", "", ()
            )

    def inherit(self, before: int, end: int, operator: str, rest: tuple[Pipeline, ...]) -> None:
        """The operator after a compound command is its last command's, when that one ends the line without its own
        (`(cd x && make) || true`)."""
        if len(self.found) == before:
            return
        last = self.found[-1]
        if not last.operator and self.line(last.command.start) == self.line(end - 1):
            last.operator, last.rest = operator, rest

    # the flags that need neighbours

    def settle(self) -> None:
        commands = self.found
        for index, found in enumerate(commands):
            line = self.line(found.command.start)
            following = commands[index + 1] if index + 1 < len(commands) else None
            if following is not None and self.line(following.command.start) == line:
                region = self.text[found.command.end : following.command.end]
            else:
                region = self.text[found.command.end : self.root.lines[line][1]]
            found.checked = bool(READS_STATUS.search(region))

    def fallback(self, found: _Found) -> str:
        """What runs after `||`, as `ShellCommand.fallback` has it: "" when it fails again (`exit 1`), tests the
        status, or goes on past the line."""
        if found.operator != "||" or not found.rest:
            return ""
        start, end = _extent(found.rest[0]), _extent(found.rest[-1])
        line = self.line(found.command.start)
        if self.line(end[1] - 1) != line or READS_STATUS.search(self.text[start[0] : end[1]]):
            return ""
        level = _Level(self.text, self.root, self.powershell)
        for pipeline in found.rest:
            level.pipeline(pipeline, "", (), "")
        commands = level.found
        if not commands or any(_fails(other.argv) for other in commands):
            return ""
        text = " ".join(commands[0].argv)
        return text if len(text) <= _FALLBACK_SHOWN else f"{commands[0].argv[0]} …"

    # the stream

    def stream(self) -> Iterator[ShellCommand | Unsplittable]:
        """Line by line: the commands of the line's substitutions, what is wrong on the line, then its own commands;
        a line's last command waits for the next line, which may read its exit status."""
        self.settle()
        by_line: dict[int, list[_Found]] = {}
        for found in self.found:
            by_line.setdefault(self.line(found.command.start), []).append(found)
        last: ShellCommand | None = None
        for index in range(len(self.root.lines)):
            text = self.line_text(index)
            if last is not None:
                yield replace(last, checked=True) if READS_STATUS.search(text) else last
            yield from self.nested_on(index)
            yield from self.errors_on(index, text)
            commands = [self.shell_command(found, text) for found in by_line.get(index, ())]
            last = commands.pop() if commands else None
            yield from commands
        if last is not None:
            yield last

    def errors_on(self, line: int, text: str) -> Iterator[Unsplittable]:
        """What is wrong on a line of the script, with where."""
        for error in self.root.errors:
            if self.line(error.offset) == line:
                yield Unsplittable(line=text, reason=error.message, span=error.span)

    def nested_on(self, line: int) -> Iterator[ShellCommand | Unsplittable]:
        """The commands of the substitutions on a line, in order, marked `nested`."""
        words = sorted((word for word in self.substitutions if self.line(word.start) == line), key=lambda w: w.start)
        for word in words:
            for substitution in word.substitutions():
                yield from map(_nested, _derived(self.text, substitution.script, self.powershell))

    def shell_command(self, found: _Found, line: str) -> ShellCommand:
        return ShellCommand(
            argv=found.argv,
            env=found.env,
            line=line,
            operator=found.operator,
            condition=found.condition,
            fallback=self.fallback(found),
            checked=found.checked,
            span=found.command.span,
        )


# A PowerShell assignment (`$x = …`, `$x += …`), and a command name its value may be the output of (`$r = gh …`).
_POWERSHELL_ASSIGNMENT = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "??="})
_POWERSHELL_COMMAND = re.compile(r"[A-Za-z][\w.-]*")


def _powershell_assigned(words: tuple[Word, ...], argv: tuple[str, ...]) -> tuple[str, ...]:
    """A PowerShell assignment is no command: what it assigns is, when that starts with a command's name."""
    if len(argv) < 2 or not argv[0].startswith("$") or argv[1] not in _POWERSHELL_ASSIGNMENT:
        return argv
    value = words[2:]
    if value and not value[0].quoted and _POWERSHELL_COMMAND.fullmatch(value[0].value):
        return argv[2:]
    return ()


def _extent(pipeline: Pipeline) -> tuple[int, int]:
    first, last = pipeline.commands[0], pipeline.commands[-1]
    start = first.start if isinstance(first, Simple) else first.command.start
    end = last.end if isinstance(last, Simple) else last.command.end
    return start, end


def _words_of(command: Simple) -> list[Word]:
    words = [assignment.value for assignment in command.assignments]
    for assignment in command.assignments:
        words.extend(assignment.elements or ())
    words.extend(command.words)
    words.extend(redirection.target for redirection in command.redirections if redirection.target is not None)
    return words


def _assigned(assignment: Assignment) -> str:
    """An assignment's value: the text after `=`, or an array's elements joined by spaces."""
    if assignment.elements is not None:
        return " ".join(element.value for element in assignment.elements)
    return assignment.value.value.split("=", 1)[1]


def _nested(found: ShellCommand | Unsplittable) -> ShellCommand | Unsplittable:
    return replace(found, nested=True) if isinstance(found, ShellCommand) else found


def _derived(text: str, script: Script, powershell: bool) -> Iterator[ShellCommand | Unsplittable]:
    level = _Level(text, script, powershell)
    level.script(script, "")
    return level.stream()


def split_script(
    script: str, opaque: re.Pattern[str] | None = None, *, powershell: bool = False
) -> Iterator[ShellCommand | Unsplittable]:
    """The simple commands of `script`, in order, each with the line it was written on; the commands of a command
    substitution come before the line they are part of.

    Text matching `opaque` (such as a CI expression the CI service evaluates before the shell runs) is kept as
    written, quotes and all, inside the word it is part of. PowerShell scripts (`powershell=True`) are split with
    PowerShell's escape character, the backquote, in place of the backslash (which is text there).
    """
    yield from _derived(script, parse(script, opaque=opaque, powershell=powershell), powershell)


__all__ = [
    "READS_STATUS",
    "ShellCommand",
    "ShellSyntaxError",
    "Unsplittable",
    "command_line",
    "quoted",
    "split_script",
    "split_words",
]
