"""Splitting the shell scripts CI runs into commands, the way a POSIX shell splits simple commands.

Only what the validator needs is understood: line continuations, comments, quoting (a quoted string may span
lines), and the operators that separate commands (`;`, `&&`, `||`, `|`, `&`). Leading `NAME=value` assignments are
the command's environment. Compound commands (`if`, `for`, `case`) and here-documents are not interpreted; their
lines are split like any other.
"""

import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass

_CONTINUATION = re.compile(r"\\\r?\n")
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", ";;", "|&"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# Words that only introduce or wrap the command that follows.
_KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}"})
_CLOSING = frozenset({"fi", "done", "esac"})
# A redirection operator (`>`, `2>&1`'s `>&`, `<<`); it and its target are not arguments.
_REDIRECTION = re.compile(r"^[<>&|]*[<>][<>&|]*$")


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellCommand:
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    line: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Unsplittable:
    """A line the shell rules above cannot split, such as one with an unbalanced quote."""

    line: str
    reason: str


_OPERATOR_CHARACTERS = ";&|()<>"
# Operator characters that are quoted or escaped are text: they stand in for them while the line is split.
_STAND_INS = {character: chr(0xE000 + index) for index, character in enumerate(_OPERATOR_CHARACTERS)}
_RESTORED = str.maketrans({stand_in: character for character, stand_in in _STAND_INS.items()})


def _protected(line: str) -> str:
    """`line` with the operator characters that are quoted (`awk -F '|'`) or escaped (`\\;`) replaced by stand-ins."""
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for character in line:
        if escaped or (quote is not None and character != quote):
            out.append(_STAND_INS.get(character, character))
            escaped = character == "\\" and quote == '"' and not escaped
            continue
        escaped = character == "\\" and quote is None
        if character in "'\"":
            quote = None if quote == character else character
        out.append(character)
    return "".join(out)


def _words(line: str) -> list[str]:
    lexer = shlex.shlex(_protected(line), posix=True, punctuation_chars=_OPERATOR_CHARACTERS)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    return list(lexer)  # quoted operator characters stay stand-ins until the commands are split (see `_command`)


def _without_redirections(words: list[str]) -> list[str]:
    kept: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
        elif _REDIRECTION.match(word):
            if kept and kept[-1].isdigit():
                kept.pop()  # the descriptor of `2>`
            skip = True
        else:
            kept.append(word)
    return kept


def _command(words: list[str], line: str) -> ShellCommand | None:
    words = _without_redirections(words)
    while words and words[0] in _KEYWORDS:
        words = words[1:]
    if words and words[0] in _CLOSING:
        return None
    env = []
    while words and _ASSIGNMENT.match(words[0]):
        name, value = words[0].split("=", 1)
        env.append((name, value.translate(_RESTORED)))
        words = words[1:]
    argv = tuple(word.translate(_RESTORED) for word in words if word not in {"(", ")"})
    return ShellCommand(argv=argv, env=tuple(env), line=line) if argv else None


def _commands_of(words: list[str], line: str) -> Iterator[ShellCommand]:
    current: list[str] = []
    for word in [*words, ";"]:
        if word in _SEPARATORS:
            if (command := _command(current, line)) is not None:
                yield command
            current = []
        else:
            current.append(word)


def _restored(command: ShellCommand, hidden: list[str]) -> ShellCommand:
    def restore(text: str) -> str:
        return _PLACEHOLDER.sub(lambda match: hidden[int(match[1])], text)

    return ShellCommand(
        argv=tuple(map(restore, command.argv)),
        env=tuple((name, restore(value)) for name, value in command.env),
        line=restore(command.line),
    )


_PLACEHOLDER = re.compile(r"__opaque_(\d+)__")


def split_script(script: str, opaque: re.Pattern[str] | None = None) -> Iterator[ShellCommand | Unsplittable]:
    """The simple commands of `script`, in order, each with the line it was written on.

    Text matching `opaque` (such as a CI expression the CI service evaluates before the shell runs) is kept as
    written, quotes and all, inside the word it is part of.
    """
    hidden: list[str] = []
    if opaque is not None:

        def hide(match: re.Match[str]) -> str:
            hidden.append(match[0])
            return f"__opaque_{len(hidden) - 1}__"

        script = opaque.sub(hide, script)
    for line, words in _lines(_CONTINUATION.sub(" ", script).splitlines()):
        if isinstance(words, ValueError):
            yield Unsplittable(line=_PLACEHOLDER.sub(lambda match: hidden[int(match[1])], line), reason=str(words))
            continue
        for command in _commands_of(words, line):
            yield _restored(command, hidden)


def _lines(raw: list[str]) -> Iterator[tuple[str, list[str] | ValueError]]:
    """Each line with its words; a quoted string that is still open at the end of a line goes on to the next."""
    lines = iter(raw)
    for first in lines:
        line = first.strip()
        if not line or line.startswith("#"):
            continue
        while True:
            try:
                yield line, _words(line)
                break
            except ValueError as error:
                following = next(lines, None)
                if following is None or "quotation" not in str(error):
                    yield line, error
                    break
                line = f"{line}\n{following}"
