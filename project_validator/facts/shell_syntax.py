"""The syntax of the shell scripts CI runs: text to a tree whose nodes say where they are.

Parsing never interprets a command; `project_validator.facts.shell` derives the simple commands from the tree. The
tree has a POSIX shell's structure: a script is a list of items (`;`, `&`, a newline), an item an and-or list of
pipelines (`&&`, `||`), a pipeline commands joined by `|`, and a command a simple command or a compound one (a
subshell, a group, `if`, `while`/`until`, `for`/`select`, `case`, a `[[ ]]` test, an arithmetic command, a function
definition). Words keep their command substitutions, parsed in turn (to `SHELL_NESTING` deep).

What CI writes is not always a whole script (a Make recipe line, a fragment), so the parser is lenient where a shell
would refuse: a compound command that is never closed ends with the script, and a closing word that closes nothing is
skipped. Only what does not split into words (an unclosed quote) is an error, and it loses its line only: the script
goes on after it (`Script.items` holds a `Malformed` in its place).

PowerShell (`powershell=True`) is split with the backquote as its escape character and without the POSIX shell's
compound commands: its lines are lists of pipelines of simple commands, keywords and braces included as words.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from project_validator.limits import SHELL_NESTING
from project_validator.parsing import ParseError, Span


class ShellSyntaxError(ParseError):
    """A command line that does not split into words (an unclosed quote)."""


class _TooDeep(ShellSyntaxError):
    """Substitutions nested past `SHELL_NESTING`: the whole line is lost, not only the innermost substitution."""


# --- the tree


@dataclass(frozen=True, slots=True)
class Text:
    """Literal text, its quotes and escapes removed."""

    text: str


@dataclass(frozen=True, slots=True)
class Substitution:
    """A command substitution (`$(…)`, `` `…` ``): its text as written, and the script it runs."""

    written: str
    script: Script


@dataclass(frozen=True, slots=True)
class Verbatim:
    """Text kept as written: an arithmetic expansion (`$((…))`), or opaque text (a CI expression)."""

    written: str


type Part = Text | Substitution | Verbatim


@dataclass(frozen=True, slots=True)
class Word:
    parts: tuple[Part, ...]
    quoted: bool
    start: int
    end: int
    span: Span

    @property
    def value(self) -> str:
        """The word as a command receives it, a substitution's text as written."""
        return "".join(part.text if isinstance(part, Text) else part.written for part in self.parts)

    def substitutions(self) -> Iterator[Substitution]:
        return (part for part in self.parts if isinstance(part, Substitution))


@dataclass(frozen=True, slots=True)
class Redirection:
    """`>file`, `2>&1`, `<<EOF` (with the here-document's body)."""

    operator: str
    target: Word | None
    descriptor: str | None = None
    body: str | None = None


@dataclass(frozen=True, slots=True)
class Assignment:
    """`NAME=value`, or `NAME=(a b)` with its elements."""

    name: str
    value: Word
    elements: tuple[Word, ...] | None = None


@dataclass(frozen=True, slots=True)
class Simple:
    assignments: tuple[Assignment, ...]
    words: tuple[Word, ...]
    redirections: tuple[Redirection, ...]
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Subshell:
    body: Script
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Group:
    body: Script
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Clause:
    """One `if`/`elif` branch: the keyword, its condition and its body."""

    keyword: str
    condition: Script
    body: Script


@dataclass(frozen=True, slots=True)
class If:
    clauses: tuple[Clause, ...]
    otherwise: Script | None
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Loop:
    """`while` or `until`."""

    keyword: str
    condition: Script
    body: Script
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class For:
    """`for` or `select`; `words` is None without `in`."""

    keyword: str
    variable: str
    words: tuple[Word, ...] | None
    body: Script
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class CaseItem:
    patterns: tuple[Word, ...]
    body: Script


@dataclass(frozen=True, slots=True)
class Case:
    subject: Word | None
    items: tuple[CaseItem, ...]
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Test:
    """`[[ … ]]`: it runs nothing; its words are its operands and operators."""

    words: tuple[Word, ...]
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Arithmetic:
    """`(( … ))`: it runs nothing."""

    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Function:
    name: str
    body: Command
    start: int
    end: int
    span: Span


type Compound = Subshell | Group | If | Loop | For | Case | Test | Arithmetic | Function
type Command = Simple | Compound


@dataclass(frozen=True, slots=True)
class Compounded:
    """A compound command with the redirections after it (`done < file`)."""

    command: Compound
    redirections: tuple[Redirection, ...]


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Commands joined by `|` or `|&` (`operators[i]` follows `commands[i]`), negated by a leading `!`."""

    commands: tuple[Simple | Compounded, ...]
    operators: tuple[str, ...]
    negated: bool


@dataclass(frozen=True, slots=True)
class AndOr:
    """Pipelines joined by `&&` or `||` (`operators[i]` follows `pipelines[i]`)."""

    pipelines: tuple[Pipeline, ...]
    operators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Item:
    """An and-or list and what ends it: `;`, `&`, `;;` (in a case), or "" (a newline, the end)."""

    list: AndOr
    terminator: str


@dataclass(frozen=True, slots=True)
class Malformed:
    """A line that does not split into words, from its start to where splitting stopped."""

    reason: str
    start: int
    end: int
    span: Span


@dataclass(frozen=True, slots=True)
class Script:
    """Items in order; `lines` are the script's logical lines (offsets: a quoted string, a substitution or a line
    continuation may make one span several physical lines), those that hold anything but a comment."""

    items: tuple[Item | Malformed, ...]
    lines: tuple[tuple[int, int], ...]
    start: int
    end: int

    def line_of(self, offset: int) -> int:
        """The index in `lines` of the line that holds `offset`."""
        return max(bisect_right(self.lines, offset, key=lambda line: line[0]) - 1, 0)


# --- splitting into tokens

REDIRECTIONS = frozenset({"<<<", "<<-", "<<", ">>", "<&", ">&", "<>", ">|", "&>>", "&>", "<", ">"})
# Longest first, so that `&&` is not read as two `&`.
_OPERATORS = sorted(
    {"&&", "||", ";;&", ";;", ";&", "|&", ";", "&", "|", "(", ")", *REDIRECTIONS}, key=len, reverse=True
)
_HEREDOC_DELIMITER = re.compile(r"[A-Za-z_][\w.-]*")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*\+?=")


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str  # word, operator, newline, number (a redirection's descriptor)
    text: str
    start: int
    end: int
    word: Word | None = None


def _is(token: _Token | None, *operators: str) -> bool:
    """Whether `token` is one of `operators` (not a word that reads the same, such as a quoted `'>'`)."""
    return token is not None and token.kind == "operator" and token.text in operators


class _Source:
    """The whole script, and positions in it as lines and columns."""

    def __init__(self, text: str, opaque: re.Pattern[str] | None, escape: str) -> None:
        self.text, self.escape = text, escape
        self.newlines = [index for index, character in enumerate(text) if character == "\n"]
        self.opaque = {match.start(): match.end() for match in opaque.finditer(text)} if opaque else {}

    def position(self, offset: int) -> tuple[int, int]:
        line = bisect_right(self.newlines, offset - 1)
        return line + 1, offset - (self.newlines[line - 1] + 1 if line else 0) + 1

    def span(self, start: int, end: int) -> Span:
        return Span(*self.position(start), *self.position(end))

    def error(self, message: str, offset: int) -> ShellSyntaxError:
        return ShellSyntaxError(message, *self.position(offset))


def _closing(text: str, start: int, end: int, escape: str = "\\") -> int | None:
    """Just after the parenthesis that closes the one at `start + 1` (in `$(`, `$((` or `<(`), or None when none does
    before `end`. A parenthesis that is quoted or escaped does not count (`$(printf ')')`)."""
    depth, quote, index = 0, "", start + 1
    ansi = False  # in `$'…'`, where a backslash escapes
    while index < end:
        character = text[index]
        if character == escape and (quote != "'" or ansi):
            index += 2
            continue
        if not quote and text.startswith("$'", index) and escape == "\\":
            quote, ansi, index = "'", True, index + 2
            continue
        if quote:
            if character == quote:
                quote, ansi = "", False
        elif character in "'\"":
            quote = character
        elif character in "()":
            depth += 1 if character == "(" else -1
            if depth == 0:
                return index + 1
        index += 1
    return None


class _Lexer:
    """The tokens of `text[start:end]`, one level of substitution deep (`depth`)."""

    def __init__(self, source: _Source, start: int, end: int, depth: int, *, powershell: bool) -> None:
        self.source, self.text, self.position, self.end = source, source.text, start, end
        self.depth, self.powershell = depth, powershell
        self.tokens: list[_Token] = []
        self.heredocs: list[tuple[str, _Token]] = []  # delimiters waiting for the next newline, with their token
        self.bodies: dict[int, str] = {}  # a here-document's body by its delimiter word's offset

    def at_continuation(self, position: int) -> int:
        """The length of the line continuation at `position` (escape, newline), or 0."""
        escape = self.source.escape
        if self.text.startswith(escape + "\n", position):
            return 2
        return 3 if self.text.startswith(escape + "\r\n", position) else 0

    def run(self) -> None:
        while self.position < self.end:
            character = self.text[self.position]
            if (skip := self.at_continuation(self.position)) or character in " \t\r":
                self.position += skip or 1
            elif character == "\n":
                self.tokens.append(_Token("newline", "\n", self.position, self.position + 1))
                self.position += 1
                self.read_heredocs()
            elif character == "#":
                newline = self.text.find("\n", self.position, self.end)
                self.position = self.end if newline < 0 else newline
            elif self.text.startswith(("<(", ">("), self.position):
                self.tokens.append(self.word())
            elif (operator := self.operator()) is not None:
                self.tokens.append(_Token("operator", operator, self.position, self.position + len(operator)))
                self.position += len(operator)
            else:
                self.tokens.append(self.word())

    def operator(self) -> str | None:
        return next(
            (operator for operator in _OPERATORS if self.text.startswith(operator, self.position, self.end)), None
        )

    def word(self) -> _Token:
        start = self.position
        reader = _WordReader(self, start)
        word = reader.read()
        token = _Token("word", word.value, start, self.position, word)
        if self.tokens and _is(self.tokens[-1], "<<", "<<-"):
            if not reader.quoted_delimiter_ok(word):
                return token
            self.heredocs.append((word.value, token))
        if word.value.isdigit() and not word.quoted and self.text.startswith(("<", ">"), self.position):
            return _Token("number", word.value, start, self.position, word)
        return token

    def read_heredocs(self) -> None:
        """Skip the bodies of the here-documents opened on the line just ended: the lines up to each delimiter."""
        while self.heredocs:
            delimiter, token = self.heredocs.pop(0)
            body_start = self.position
            while self.position < self.end:
                newline = self.text.find("\n", self.position, self.end)
                line_end = self.end if newline < 0 else newline
                line = self.text[self.position : line_end]
                self.position = line_end + 1 if newline >= 0 else self.end
                if line.strip() == delimiter:
                    self.bodies[token.start] = self.text[body_start : line_end - len(line)]
                    break
            else:
                self.bodies[token.start] = self.text[body_start : self.end]


class _WordReader:
    """One word: its parts, from unquoted, single-quoted and double-quoted text, substitutions and opaque text."""

    def __init__(self, lexer: _Lexer, start: int) -> None:
        self.lexer, self.source, self.text, self.start = lexer, lexer.source, lexer.text, start
        self.parts: list[Part] = []
        self.literal: list[str] = []
        self.quoted = False

    def flush(self) -> None:
        if self.literal:
            self.parts.append(Text("".join(self.literal)))
            self.literal = []

    def add(self, part: Part) -> None:
        self.flush()
        self.parts.append(part)

    def read(self) -> Word:
        lexer = self.lexer
        while lexer.position < lexer.end and not self.ends_word(lexer.position):
            self.step(quote="")
        self.flush()
        position = lexer.position
        return Word(tuple(self.parts), self.quoted, self.start, position, self.source.span(self.start, position))

    def ends_word(self, position: int) -> bool:
        character = self.text[position]
        if position == self.start and self.text.startswith(("<(", ">("), position):
            return False  # a process substitution starts the word
        if character in " \t\r\n" or self.lexer.at_continuation(position):
            return True
        return character in ";&|()<>" and position not in self.source.opaque

    def step(self, quote: str) -> None:
        """Read what starts at the lexer's position, inside `quote` ("", or `"`)."""
        lexer, position, escape = self.lexer, self.lexer.position, self.source.escape
        character = self.text[position]
        if position in self.source.opaque:
            self.add(Verbatim(self.text[position : self.source.opaque[position]]))
            lexer.position = self.source.opaque[position]
        elif self.expansion(position, quote):
            return
        elif character == escape:
            self.escaped(position, quote)
        elif character == "'" and not quote:
            self.single_quoted(position)
        elif character == "$" and not quote and self.text.startswith("$'", position) and escape == "\\":
            self.ansi_c_quoted(position)
        elif character == '"' and not quote:
            self.double_quoted(position)
        else:
            self.literal.append(character)
            lexer.position += 1

    def escaped(self, position: int, quote: str) -> None:
        if (skip := self.lexer.at_continuation(position)) and quote:
            self.literal.append(" ")  # a continuation joins the lines with a space, quoted or not
            self.lexer.position += skip
            return
        if position + 1 >= self.lexer.end:
            raise self.source.error("No escaped character", position)
        following = self.text[position + 1]
        if quote and following not in (quote, self.source.escape):
            self.literal.append(self.text[position : position + 2])  # in double quotes an escape is mostly text
        else:
            self.literal.append(following)
        self.lexer.position += 2

    def single_quoted(self, position: int) -> None:
        self.quoted = True
        lexer = self.lexer
        lexer.position = position + 1
        while lexer.position < lexer.end and self.text[lexer.position] != "'":
            here = lexer.position
            if here in self.source.opaque:
                self.add(Verbatim(self.text[here : self.source.opaque[here]]))
                lexer.position = self.source.opaque[here]
            elif skip := lexer.at_continuation(here):
                self.literal.append(" ")
                lexer.position += skip
            else:
                self.literal.append(self.text[here])
                lexer.position += 1
        if lexer.position >= lexer.end:
            raise self.source.error("No closing quotation", position)
        lexer.position += 1

    def ansi_c_quoted(self, position: int) -> None:
        """`$'…'`: single-quoted, except that a backslash escapes (`\\'` is a quote); escapes other than of a quote
        or a backslash are kept as written."""
        self.quoted = True
        lexer = self.lexer
        lexer.position = position + 2
        while lexer.position < lexer.end and self.text[lexer.position] != "'":
            here = lexer.position
            if self.text[here] == "\\" and here + 1 < lexer.end:
                following = self.text[here + 1]
                self.literal.append(following if following in "'\\" else self.text[here : here + 2])
                lexer.position += 2
            else:
                self.literal.append(self.text[here])
                lexer.position += 1
        if lexer.position >= lexer.end:
            raise self.source.error("No closing quotation", position)
        lexer.position += 1

    def double_quoted(self, position: int) -> None:
        self.quoted = True
        lexer = self.lexer
        lexer.position = position + 1
        while lexer.position < lexer.end and self.text[lexer.position] != '"':
            self.step(quote='"')
        if lexer.position >= lexer.end:
            raise self.source.error("No closing quotation", position)
        lexer.position += 1

    def expansion(self, position: int, quote: str) -> bool:
        """Read an arithmetic expansion or a command substitution starting at `position`; whether one does."""
        lexer, text = self.lexer, self.text
        if (
            text.startswith("$((", position)
            and (end := _closing(text, position, lexer.end, self.source.escape)) is not None
        ):
            self.add(Verbatim(text[position:end]))
        elif text.startswith("${", position):
            self.parameter(position, quote)
            return True
        elif self.opens_substitution(position):
            if (end := _closing(text, position, lexer.end, self.source.escape)) is None:
                return False
            self.add(Substitution(text[position:end], self.inner(position + 2, end - 1)))
        elif text.startswith("`", position) and self.source.escape != "`":
            if (close := text.find("`", position + 1, lexer.end)) < 0:
                return False
            end = close + 1
            self.add(Substitution(text[position:end], self.inner(position + 1, close)))
        else:
            return False
        lexer.position = end
        return True

    def parameter(self, position: int, quote: str) -> None:
        """`${…}`, up to its closing brace, as written; quotes and substitutions in it are read as anywhere else (a
        substitution runs: `${JOBS:-$(nproc)}`), by the quoting it is in (`quote`)."""
        lexer, depth = self.lexer, 0
        self.literal.append("${")
        lexer.position = position + 2
        while lexer.position < lexer.end:
            character = self.text[lexer.position]
            if character == "}" and depth == 0:
                self.literal.append("}")
                lexer.position += 1
                return
            depth += {"{": 1, "}": -1}.get(character, 0)
            self.step(quote=quote)
        raise self.source.error("No closing brace", position)

    def opens_substitution(self, position: int) -> bool:
        """Whether `$(` (not `$((`) starts at `position`, or a process substitution (`<(`, `>(`) starts the word."""
        if self.text.startswith("$(", position):
            return not self.text.startswith("$((", position)
        return position == self.start and self.text.startswith(("<(", ">("), position)

    def inner(self, start: int, end: int) -> Script:
        return _parse(self.source, start, end, self.lexer.depth + 1, powershell=self.lexer.powershell)

    def quoted_delimiter_ok(self, word: Word) -> bool:
        """Whether a word after `<<` delimits a here-document (a name, quoted or not)."""
        return _HEREDOC_DELIMITER.fullmatch(word.value) is not None


# --- parsing the tokens


_RESERVED = frozenset(
    {"if", "then", "elif", "else", "fi", "do", "done", "case", "esac", "while", "until", "for", "select", "in"}
    | {"function", "{", "}", "!", "[[", "]]"}
)
_CLOSERS = frozenset({"then", "elif", "else", "fi", "do", "done", "esac", "}"})
_LIST_TERMINATORS = frozenset({";", "&", ";;", ";&", ";;&"})


class _Parser:
    def __init__(self, source: _Source, tokens: list[_Token], bodies: dict[int, str], *, powershell: bool) -> None:
        self.source, self.tokens, self.bodies, self.powershell = source, tokens, bodies, powershell
        self.index = 0
        self.stops: list[frozenset[str]] = []
        self.open_subshells = 0

    # tokens

    def peek(self, offset: int = 0) -> _Token | None:
        index = self.index + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def reserved(self, *words: str) -> bool:
        """Whether the next token is one of the reserved `words`, as written (unquoted)."""
        token = self.peek()
        return (
            not self.powershell
            and token is not None
            and token.kind == "word"
            and token.word is not None
            and not token.word.quoted
            and token.text in words
        )

    def operator(self, *operators: str) -> bool:
        token = self.peek()
        return _is(token, *operators)

    def newlines(self) -> None:
        while (token := self.peek()) is not None and token.kind == "newline":
            self.index += 1

    def span(self, start: int, end: int) -> Span:
        return self.source.span(start, end)

    def last_end(self, default: int) -> int:
        return self.tokens[self.index - 1].end if self.index else default

    # lists

    def script(self, start: int, stop: frozenset[str] = frozenset(), *, line: bool = False) -> Script:
        """Items up to a word in `stop` (or a stop of an enclosing command), the `)` of an open subshell, or the end;
        with `line`, only to the end of the line."""
        items: list[Item | Malformed] = []
        self.stops.append(stop)
        while True:
            if not line:
                self.newlines()
            token = self.peek()
            if token is None or token.kind == "newline" or self.reserved(*self.stopping()):
                break
            if self.operator(")") and self.open_subshells:
                break
            if self.reserved(*_CLOSERS) or self.operator(")", *_LIST_TERMINATORS):
                self.index += 1  # closes nothing here: skipped
                continue
            items.append(self.item())
        self.stops.pop()
        return Script(tuple(items), (), start, self.last_end(start))

    def stopping(self) -> frozenset[str]:
        return frozenset().union(*self.stops)

    def item(self) -> Item:
        and_or = self.and_or()
        terminator = ""
        if self.operator(*_LIST_TERMINATORS):
            terminator = self.take().text
        return Item(and_or, terminator)

    def and_or(self) -> AndOr:
        pipelines, operators = [self.pipeline()], []
        while self.operator("&&", "||"):
            operators.append(self.take().text)
            self.newlines()
            pipelines.append(self.pipeline())
        return AndOr(tuple(pipelines), tuple(operators))

    def pipeline(self) -> Pipeline:
        negated = self.reserved("!")
        if negated:
            self.index += 1
        commands, operators = [self.command()], []
        while self.operator("|", "|&"):
            operators.append(self.take().text)
            self.newlines()
            commands.append(self.command())
        return Pipeline(tuple(commands), tuple(operators), negated)

    # commands

    def command(self) -> Simple | Compounded:
        start = self.peek().start if self.peek() is not None else 0  # type: ignore[union-attr]
        compound = self.compound(start)
        if compound is None:
            return self.simple(start)
        return Compounded(compound, self.redirections())

    def compound(self, start: int) -> Compound | None:
        if self.powershell:
            return None
        token = self.peek()
        if token is None:
            return None
        if _is(token, "("):
            return self.arithmetic(start) if self.adjacent("(") else self.subshell(start)
        keyword = token.text if self.reserved(*_COMPOUNDS) else None
        if keyword is not None:
            return _COMPOUNDS[keyword](self, start)
        if self.function_name():
            return self.function(start, token.text)
        return None

    def adjacent(self, text: str) -> bool:
        """Whether the token after the next is `text`, written right after it (`((`)."""
        first, second = self.peek(), self.peek(1)
        return first is not None and _is(second, text) and second.start == first.end  # type: ignore[union-attr]

    def function_name(self) -> bool:
        """Whether a function definition starts here: `name()`."""
        token, opening, closing = self.peek(), self.peek(1), self.peek(2)
        return token is not None and token.kind == "word" and _is(opening, "(") and _is(closing, ")")

    def simple(self, start: int) -> Simple:
        assignments: list[Assignment] = []
        words: list[Word] = []
        redirections: list[Redirection] = []
        while (token := self.peek()) is not None and token.kind != "newline":
            if token.kind == "operator" and token.text not in REDIRECTIONS and token.text != "(":
                if token.text != ")" or not self.stray_parenthesis():
                    break
                self.index += 1
            elif token.kind == "number" or _is(token, *REDIRECTIONS):
                redirections.append(self.redirection())
            elif _is(token, "("):
                self.index += 1  # not a command's start: text a shell would refuse, dropped
            elif not words and token.word is not None and _ASSIGNMENT.match(token.text):
                assignments.append(self.assignment())
            else:
                words.append(self.take().word)  # type: ignore[arg-type]
        end = self.last_end(start)
        return Simple(tuple(assignments), tuple(words), tuple(redirections), start, end, self.span(start, end))

    def stray_parenthesis(self) -> bool:
        """Whether a `)` closes nothing: no subshell is open (see `subshell`)."""
        return self.open_subshells == 0

    def assignment(self) -> Assignment:
        token = self.take()
        word = token.word
        assert word is not None  # noqa: S101 - a word token has its word
        name = token.text.split("=", 1)[0].removesuffix("+")
        following = self.peek()
        if token.text.endswith("=") and _is(following, "(") and following.start == token.end:  # type: ignore[union-attr]
            self.index += 1
            elements: list[Word] = []
            while (element := self.peek()) is not None and not _is(element, ")"):
                self.index += 1
                if element.word is not None:
                    elements.append(element.word)
            if element is not None:
                self.index += 1
            return Assignment(name, word, tuple(elements))
        return Assignment(name, word)

    def redirection(self) -> Redirection:
        descriptor = self.take().text if self.peek() is not None and self.peek().kind == "number" else None  # type: ignore[union-attr]
        operator = self.take().text if self.peek() is not None and self.peek().kind == "operator" else ""  # type: ignore[union-attr]
        target = None
        if (token := self.peek()) is not None and token.kind in ("word", "number"):
            self.index += 1
            target = token.word
        body = self.bodies.get(token.start) if token is not None and target is not None else None
        return Redirection(operator, target, descriptor, body)

    def redirections(self) -> tuple[Redirection, ...]:
        found = []
        while (token := self.peek()) is not None and (token.kind == "number" or _is(token, *REDIRECTIONS)):
            found.append(self.redirection())
        return tuple(found)

    # compound commands

    def finish(self, keyword: str) -> None:
        if self.reserved(keyword):
            self.index += 1

    def body(self, start: int, *stop: str) -> Script:
        return self.script(start, frozenset(stop))

    def condition(self, start: int, *stop: str) -> Script | None:
        """A condition up to the word that opens its body; None, with nothing read, when the script ends before that
        word (a fragment, or another shell's `if`): the caller reads only the rest of the line as the condition."""
        mark = self.index
        condition = self.body(start, *stop)
        if self.peek() is None:
            self.index = mark
            return None
        return condition

    def empty(self, start: int) -> Script:
        return Script((), (), start, start)

    def subshell(self, start: int) -> Subshell:
        self.index += 1
        self.open_subshells += 1
        body = self.script(start)
        self.open_subshells -= 1
        if self.operator(")"):
            self.index += 1
        end = self.last_end(start)
        return Subshell(body, start, end, self.span(start, end))

    def arithmetic(self, start: int) -> Arithmetic:
        self.index += 2
        depth = 2
        while (token := self.peek()) is not None and depth > 0:
            self.index += 1
            depth += {"(": 1, ")": -1}.get(token.text, 0)
        end = self.last_end(start)
        return Arithmetic(start, end, self.span(start, end))

    def group(self, start: int) -> Group:
        self.index += 1
        body = self.body(start, "}")
        self.finish("}")
        end = self.last_end(start)
        return Group(body, start, end, self.span(start, end))

    def if_(self, start: int) -> If:
        clauses, otherwise = [], None
        while self.reserved("if", "elif"):
            keyword = self.take().text
            condition = self.condition(start, "then", "elif", "else", "fi")
            if condition is None:  # no `then`: its own line was the condition, and it has no body
                clauses.append(Clause(keyword, self.script(start, line=True), self.empty(start)))
                break
            self.finish("then")
            clauses.append(Clause(keyword, condition, self.body(start, "elif", "else", "fi")))
        if self.reserved("else"):
            self.index += 1
            otherwise = self.body(start, "fi")
        self.finish("fi")
        end = self.last_end(start)
        return If(tuple(clauses), otherwise, start, end, self.span(start, end))

    def loop(self, start: int) -> Loop:
        keyword = self.take().text
        condition = self.condition(start, "do", "done")
        if condition is None:  # no `do`
            condition, body = self.script(start, line=True), self.empty(start)
            end = self.last_end(start)
            return Loop(keyword, condition, body, start, end, self.span(start, end))
        self.finish("do")
        body = self.body(start, "done")
        self.finish("done")
        end = self.last_end(start)
        return Loop(keyword, condition, body, start, end, self.span(start, end))

    def for_(self, start: int) -> For:
        keyword = self.take().text
        variable = self.take().text if self.peek() is not None and self.peek().kind == "word" else ""  # type: ignore[union-attr]
        if not variable and self.operator("("):
            self.arithmetic(start)  # for (( … ))
        words = self.for_words()
        self.newlines()
        self.finish("do")
        body = self.body(start, "done")
        self.finish("done")
        end = self.last_end(start)
        return For(keyword, variable, words, body, start, end, self.span(start, end))

    def for_words(self) -> tuple[Word, ...] | None:
        self.newlines()
        if not self.reserved("in"):
            if self.operator(";"):
                self.index += 1
            return None
        self.index += 1
        words = []
        while (token := self.peek()) is not None and token.kind == "word" and not self.reserved("do"):
            words.append(self.take().word)
        if self.operator(";"):
            self.index += 1
        return tuple(word for word in words if word is not None)

    def case(self, start: int) -> Case:
        self.index += 1
        subject = self.take().word if self.peek() is not None and self.peek().kind == "word" else None  # type: ignore[union-attr]
        self.newlines()
        self.finish("in")
        items = []
        while True:
            self.newlines()
            if self.peek() is None or self.reserved("esac"):
                break
            items.append(self.case_item(start))
        self.finish("esac")
        end = self.last_end(start)
        return Case(subject, tuple(items), start, end, self.span(start, end))

    def case_item(self, start: int) -> CaseItem:
        if self.operator("("):
            self.index += 1
        patterns = []
        while (token := self.peek()) is not None and not self.operator(")") and token.kind != "newline":
            self.index += 1
            if token.word is not None:
                patterns.append(token.word)
        if self.operator(")"):
            self.index += 1
        items: list[Item | Malformed] = []
        while True:
            self.newlines()
            if self.peek() is None or self.reserved("esac"):
                break
            item = self.item()
            items.append(item)
            if item.terminator in (";;", ";&", ";;&"):
                break
        return CaseItem(tuple(patterns), Script(tuple(items), (), start, self.last_end(start)))

    def test(self, start: int) -> Test:
        self.index += 1
        words = []
        while (token := self.peek()) is not None and not self.reserved("]]"):
            self.index += 1
            if token.word is not None:
                words.append(token.word)
        self.finish("]]")
        end = self.last_end(start)
        return Test(tuple(words), start, end, self.span(start, end))

    def function_keyword(self, start: int) -> Function:
        return self.function(start, "")

    def function(self, start: int, name: str) -> Function:
        """`name() body`, `function name body` or `function name() body`."""
        if self.reserved("function"):
            self.index += 1
            name = self.take().text if self.peek() is not None else ""
        else:
            self.index += 1  # the name
        if self.operator("(") and _is(self.peek(1), ")"):
            self.index += 2
        self.newlines()
        body = self.command()
        end = self.last_end(start)
        return Function(name, body.command if isinstance(body, Compounded) else body, start, end, self.span(start, end))


_COMPOUNDS: dict[str, Callable[[_Parser, int], Compound]] = {
    "if": _Parser.if_,
    "while": _Parser.loop,
    "until": _Parser.loop,
    "for": _Parser.for_,
    "select": _Parser.for_,
    "case": _Parser.case,
    "{": _Parser.group,
    "[[": _Parser.test,
    "function": _Parser.function_keyword,
}


# --- lines, errors and the whole


def _lines(tokens: list[_Token], end: int) -> list[tuple[int, int]]:
    """The logical lines that hold tokens: from the first token after a newline to that newline (comments included)."""
    lines: list[tuple[int, int]] = []
    line_start: int | None = None
    for token in tokens:
        if token.kind == "newline":
            if line_start is not None:
                lines.append((line_start, token.start))
            line_start = None
        elif line_start is None:
            line_start = token.start
    if line_start is not None:
        lines.append((line_start, end))
    return lines


def _line_start(tokens: list[_Token], start: int) -> int:
    """Where the line being split started: after the last newline token (the line's tokens are dropped)."""
    while tokens and tokens[-1].kind != "newline":
        tokens.pop()
    return tokens[-1].end if tokens else start


def _parse(source: _Source, start: int, end: int, depth: int, *, powershell: bool) -> Script:
    if not SHELL_NESTING.allows(depth):
        raise _TooDeep(SHELL_NESTING.reason, *source.position(start))
    segments: list[tuple[list[_Token], dict[int, str], Malformed | None]] = []
    position = start
    while position < end:
        lexer = _Lexer(source, position, end, depth, powershell=powershell)
        try:
            lexer.run()
        except ShellSyntaxError as error:
            if isinstance(error, _TooDeep) and depth > 0:
                raise
            line_start = _line_start(lexer.tokens, position)
            stop = _malformed_end(source, error, line_start, end)
            segments.append(
                (lexer.tokens, lexer.bodies, Malformed(error.message, line_start, stop, source.span(line_start, stop)))
            )
            position = stop
            continue
        segments.append((lexer.tokens, lexer.bodies, None))
        break
    return _parsed(source, segments, start, end, powershell=powershell)


def _malformed_end(source: _Source, error: ShellSyntaxError, line_start: int, end: int) -> int:
    """Where a malformed line ends: an unclosed quote takes the rest of the script; a line nested too deeply, its
    physical line."""
    if not isinstance(error, _TooDeep):
        return end
    newline = source.text.find("\n", line_start, end)
    return end if newline < 0 else newline


def _parsed(
    source: _Source,
    segments: list[tuple[list[_Token], dict[int, str], Malformed | None]],
    start: int,
    end: int,
    *,
    powershell: bool,
) -> Script:
    items: list[Item | Malformed] = []
    lines: list[tuple[int, int]] = []
    for tokens, bodies, malformed in segments:
        script = _Parser(source, tokens, bodies, powershell=powershell).script(start)
        items.extend(script.items)
        lines.extend(_lines(tokens, end if malformed is None else malformed.start))
        if malformed is not None:
            items.append(malformed)
            lines.append((malformed.start, malformed.end))
    return Script(tuple(items), tuple(lines), start, end)


def parse(script: str, *, opaque: re.Pattern[str] | None = None, powershell: bool = False) -> Script:
    """The tree of `script`. Text matching `opaque` (a CI expression the CI service evaluates first) is kept as
    written, quotes and all, inside the word it is part of."""
    source = _Source(script, opaque, "`" if powershell else "\\")
    return _parse(source, 0, len(script), 0, powershell=powershell)
