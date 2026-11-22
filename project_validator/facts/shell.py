"""Splitting the shell scripts CI runs into commands, the way a POSIX shell splits simple commands.

Only what the validator needs is understood: line continuations, comments, quoting (a quoted string may span
lines), the operators that separate commands (`;`, `&&`, `||`, `|`, `&`), and command substitution (`$(…)` and
backquotes), whose commands run before the command they are part of. PowerShell scripts (`powershell=True`) are split
the same way, with PowerShell's escape character, the backquote, in place of the backslash (which is text there).
Leading `NAME=value` assignments (and arrays, `NAME=(a b)`) are the command's environment; a conditional expression,
`[[ … ]]`, runs nothing, over as many lines as it takes, and the body of a here-document is data, not commands.
Compound commands (`if`, `for`, `case`) are not interpreted; their lines are split like any other.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace

from project_validator.parsing import ParseError


class ShellSyntaxError(ParseError):
    """A command line that does not split into words (an unclosed quote)."""


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


_CONTINUATION = re.compile(r"\\\r?\n")
_POWERSHELL_CONTINUATION = re.compile(r"`\r?\n")
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", ";;", "|&"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# Words that only introduce or wrap the command that follows.
_KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}"})
_CLOSING = frozenset({"fi", "done", "esac"})
# A redirection operator (`>`, `2>&1`'s `>&`, `<<`); it and its target are not arguments.
_REDIRECTION = re.compile(r"^[<>&|]*[<>][<>&|]*$")


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


@dataclass(frozen=True, slots=True, kw_only=True)
class Unsplittable:
    """A line the shell rules above cannot split, such as one with an unbalanced quote."""

    line: str
    reason: str


_OPERATOR_CHARACTERS = ";&|()<>"
# Operator characters that are quoted or escaped are text: they stand in for them while the line is split.
_STAND_INS = {character: chr(0xE000 + index) for index, character in enumerate(_OPERATOR_CHARACTERS)}
_RESTORED = str.maketrans({stand_in: character for character, stand_in in _STAND_INS.items()})


def _protected(line: str, escape: str = "\\") -> str:
    """`line` with the operator characters that are quoted (`awk -F '|'`) or escaped (`\\;`) replaced by stand-ins."""
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for character in line:
        if escaped or (quote is not None and character != quote):
            out.append(_STAND_INS.get(character, character))
            escaped = character == escape and quote == '"' and not escaped
            continue
        escaped = character == escape and quote is None
        if character in "'\"":
            quote = None if quote == character else character
        out.append(character)
    return "".join(out)


# A `#` begins a comment at the start of a word only (`.#checks` is one word); shlex would end the word there.
_HASH_IN_WORD = re.compile(r"(?<=\S)#")
_HASH_STAND_IN = chr(0xE000 + len(_OPERATOR_CHARACTERS))


def _words(line: str, escape: str = "\\") -> list[str]:
    protected = _HASH_IN_WORD.sub(_HASH_STAND_IN, _protected(line, escape))
    lexer = shlex.shlex(protected, posix=True, punctuation_chars=_OPERATOR_CHARACTERS)
    lexer.escape = escape
    lexer.whitespace_split = True
    lexer.commenters = "#"
    # Quoted operator characters stay stand-ins until the commands are split (see `_command`).
    return [word.replace(_HASH_STAND_IN, "#") for word in lexer]


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


def _without_compound_headers(words: list[str]) -> list[str]:
    """`words` without what only opens a compound command: a `for`/`select` header (it assigns, it runs nothing), a
    `case WORD in` header, and a case clause's pattern (`a)`, when commands follow it; a `)` with none after it ends a
    subshell)."""
    if words[:1] in (["for"], ["select"]):
        return []
    if words[:1] == ["case"]:
        words = words[words.index("in") + 1 :] if "in" in words else []
    if ")" in words and "(" not in words[: (close := words.index(")"))] and close + 1 < len(words):
        words = words[close + 1 :]
    return words


def _command(words: list[str], line: str) -> ShellCommand | None:
    words = _without_redirections(words)
    while words and words[0] in _KEYWORDS:
        words = words[1:]
    words = _without_compound_headers(words)
    if words and words[0] in _CLOSING:
        return None
    env = []
    while words and _ASSIGNMENT.match(words[0]):
        name, value = words[0].split("=", 1)
        words = words[1:]
        if not value and words[:1] == ["("] and ")" in words:
            # An array assignment, `name=(a b)`: its elements are its value, not a command.
            close = words.index(")")
            value, words = " ".join(words[1:close]), words[close + 1 :]
        env.append((name, value.translate(_RESTORED)))
    argv = tuple(word.translate(_RESTORED) for word in words if word not in {"(", ")"})
    return ShellCommand(argv=argv, env=tuple(env), line=line) if argv else None


_CONDITIONS = frozenset({"if", "elif", "while", "until"})
_BODIES = frozenset({"then", "do"})
# What reads the exit status of the command before.
READS_STATUS = re.compile(r"\$\?|\$\{\?\}|PIPESTATUS")
# The operators that end a list of commands; the others (`&&`, `||`, `|`) join it to the next.
_LIST_ENDS = frozenset({"", ";", ";;", "&"})


@dataclass(frozen=True, slots=True)
class _Segment:
    """The words between two operators, the operator after them ("" at the line's end), and whether they read the
    exit status of the command before."""

    words: list[str]
    operator: str
    reads: bool


def _segments(words: list[str]) -> Iterator[_Segment]:
    current: list[str] = []
    testing = reads = False
    for word in words:
        reads = reads or bool(READS_STATUS.search(word))
        # A conditional expression, `[[ … ]]`, runs nothing: its words (and its `||`, `&&`) are not commands.
        if testing:
            testing = word != "]]"
            continue
        if word == "[[" and all(kept in _KEYWORDS for kept in current):
            testing = True
            continue
        if word in _SEPARATORS:
            yield _Segment(current, word, reads)
            current, reads = [], False
        else:
            current.append(word)
    yield _Segment(current, "", reads)


def _commands_of(words: list[str], line: str) -> list[ShellCommand]:
    found: list[ShellCommand] = []
    segments = list(_segments(words))
    condition = ""
    for index, segment in enumerate(segments):
        leading = segment.words[: next((at for at, word in enumerate(segment.words) if word not in _KEYWORDS), None)]
        for keyword in leading:
            condition = keyword if keyword in _CONDITIONS else "" if keyword in _BODIES else condition
        if segment.reads and found:
            found[-1] = replace(found[-1], checked=True)
        if (command := _command(segment.words, line)) is not None:
            fallback = _fallback(segments[index + 1 :]) if segment.operator == "||" else ""
            negated = "!" if "!" in leading else ""
            found.append(replace(command, operator=segment.operator, condition=condition or negated, fallback=fallback))
    return found


def _fails(argv: tuple[str, ...]) -> bool:
    """Whether a command fails whatever came before: `false`, or an `exit`/`return` other than `exit 0`."""
    return argv[:1] == ("false",) or (argv[:1] in (("exit",), ("return",)) and argv[1:2] != ("0",))


def _fallback(rest: list[_Segment]) -> str:
    """What runs after `||` (`rest`, to the line's end), as `ShellCommand.fallback` has it: "" when it fails again
    (`exit 1`), tests the status, or goes on past the line."""
    depth, first = 0, None
    for segment in rest:
        depth += sum(word.count("{") + word.count("(") - word.count("}") - word.count(")") for word in segment.words)
        command = _command(segment.words, "")
        # A fallback that tests the status (`|| [ $? -eq 124 ]`) fails again on all it does not accept.
        if segment.reads or (command is not None and _fails(command.argv)):
            return ""
        first = first or command
        if depth <= 0 and segment.operator in _LIST_ENDS:
            break
    if depth > 0 or first is None:
        return ""
    text = " ".join(word.translate(_RESTORED) for word in first.argv)
    return text if len(text) <= _FALLBACK_SHOWN else f"{first.argv[0]} …"


# The longest fallback named whole; a longer one is named by its program.
_FALLBACK_SHOWN = 24


_PLACEHOLDER = re.compile(r"__opaque_(\d+)__")


@dataclass(slots=True)
class _Hidden:
    """The text hidden from the splitter while a script is split, by placeholder: opaque text, and command
    substitutions with the commands they run."""

    texts: list[str] = field(default_factory=list)
    substitutions: dict[int, str] = field(default_factory=dict)

    def shown(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda match: self.texts[int(match[1])], text)

    def hide(self, text: str, commands: str | None = None) -> str:
        self.texts.append(self.shown(text))
        if commands is not None:
            self.substitutions[len(self.texts) - 1] = self.shown(commands)
        return f"__opaque_{len(self.texts) - 1}__"

    def substituted(self, line: str) -> list[str]:
        """The commands of the command substitutions in `line`."""
        return [
            self.substitutions[index] for index in map(int, _PLACEHOLDER.findall(line)) if index in self.substitutions
        ]

    def restored(self, command: ShellCommand) -> ShellCommand:
        return replace(
            command,
            argv=tuple(map(self.shown, command.argv)),
            env=tuple((name, self.shown(value)) for name, value in command.env),
            line=self.shown(command.line),
        )


def split_script(
    script: str, opaque: re.Pattern[str] | None = None, *, powershell: bool = False
) -> Iterator[ShellCommand | Unsplittable]:
    """The simple commands of `script`, in order, each with the line it was written on; the commands of a command
    substitution come before the command it is part of.

    Text matching `opaque` (such as a CI expression the CI service evaluates before the shell runs) is kept as
    written, quotes and all, inside the word it is part of.
    """
    try:
        found = list(_split_script(script, opaque, powershell=powershell))
    except RecursionError:
        # Line by line, so only the lines nested too deeply are lost.
        found = []
        for line in script.splitlines():
            try:
                found.extend(_split_script(line, opaque, powershell=powershell))
            except RecursionError:
                found.append(Unsplittable(line=line, reason="nested too deeply to split"))
    yield from found


def _split_script(
    script: str, opaque: re.Pattern[str] | None, *, powershell: bool
) -> Iterator[ShellCommand | Unsplittable]:
    hidden = _Hidden()
    # Opaque text first: a Make variable `$(CC)` is not a command substitution.
    if opaque is not None:
        script = opaque.sub(lambda match: hidden.hide(match[0]), script)
    escape = "`" if powershell else "\\"
    script = _substitutions(_without_heredocs(script), hidden.hide, escape)
    continuation = _POWERSHELL_CONTINUATION if powershell else _CONTINUATION
    # Each line's last command waits for the next line, which may read its exit status.
    last: ShellCommand | None = None
    for line, words in _lines(continuation.sub(" ", script).splitlines(), escape):
        if last is not None:
            yield replace(last, checked=True) if READS_STATUS.search(hidden.shown(line)) else last
            last = None
        for commands in hidden.substituted(line):
            yield from map(_nested, _split_script(commands, opaque, powershell=powershell))
        if isinstance(words, ValueError):
            yield Unsplittable(line=hidden.shown(line), reason=str(words))
            continue
        found = [hidden.restored(command) for command in _commands_of(words, line)]
        if found:
            yield from found[:-1]
            last = found[-1]
    if last is not None:
        yield last


def _nested(found: ShellCommand | Unsplittable) -> ShellCommand | Unsplittable:
    return replace(found, nested=True) if isinstance(found, ShellCommand) else found


# A here-document's operator and its delimiter word (`<<EOF`, `<<-'EOF'`, `<< "END"`); not a here-string (`<<<`).
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1")


def _without_heredocs(script: str) -> str:
    """`script` without the bodies of its here-documents: the lines after `<<WORD`, up to the line that is `WORD`,
    are data the command reads, not commands."""
    kept: list[str] = []
    pending: list[str] = []
    for line in script.splitlines():
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [match[2] for match in _HEREDOC.finditer(line.split(" #", 1)[0])]
    return "\n".join(kept)


def _substitutions(script: str, hide: Callable[[str, str | None], str], escape: str = "\\") -> str:
    """`script` with each command substitution outside single quotes (`$(…)`, and `` `…` `` where the backquote is no
    escape; not arithmetic `$((…))`) replaced by what `hide` returns for its text and its commands."""
    out: list[str] = []
    index, quote = 0, ""
    while index < len(script):
        character = script[index]
        if quote != "'" and (arithmetic := _arithmetic_end(script, index)) is not None:
            out.append(hide(script[index:arithmetic], None))  # a value: kept whole, it runs nothing
            index = arithmetic
            continue
        end = None if quote == "'" else _substitution_end(script, index, backquotes=escape != "`")
        if end is not None:
            text = script[index:end]
            out.append(hide(text, text[2:-1] if text.startswith("$(") else text[1:-1]))
            index = end
            continue
        if character == escape and quote != "'":
            out.append(script[index : index + 2])
            index += 2
            continue
        if character in "'\"" and quote in ("", character):
            quote = "" if quote else character
        out.append(character)
        index += 1
    return "".join(out)


def _closing(script: str, start: int) -> int | None:
    """Just after the parenthesis that closes the one at `start + 1` (`$(` or `$((`), or None when none does."""
    depth = 0
    for index in range(start + 1, len(script)):
        depth += {"(": 1, ")": -1}.get(script[index], 0)
        if depth == 0:
            return index + 1
    return None


def _arithmetic_end(script: str, start: int) -> int | None:
    """Where the arithmetic expansion `$((…))` starting at `start` ends (just after it); None if none starts there."""
    return _closing(script, start) if script.startswith("$((", start) else None


def _substitution_end(script: str, start: int, *, backquotes: bool = True) -> int | None:
    """Where the command substitution starting at `start` ends (just after it), or None if none starts there."""
    if backquotes and script.startswith("`", start):
        end = script.find("`", start + 1)
        return None if end < 0 else end + 1
    if not script.startswith("$(", start) or script.startswith("$((", start):
        return None
    return _closing(script, start)


def _lines(raw: list[str], escape: str = "\\") -> Iterator[tuple[str, list[str] | ValueError]]:
    """Each line with its words; a quoted string that is still open at the end of a line goes on to the next."""
    lines = iter(raw)
    for first in lines:
        line = first.strip()
        if not line or line.startswith("#"):
            continue
        while True:
            try:
                words = _words(line, escape)
            except ValueError as error:
                following = next(lines, None)
                if following is None or "quotation" not in str(error):
                    yield line, error
                    break
                line = f"{line}\n{following}"
                continue
            # A `[[ … ]]` test may go on over several lines (`a ||` at the end of one); it is one command.
            following = next(lines, None) if _open_test(words) else None
            if following is None:
                yield line, words
                break
            line = f"{line} {following.strip()}"


def _open_test(words: list[str]) -> bool:
    """Whether the words open more `[[` tests than they close."""
    return words.count("[[") > words.count("]]")
