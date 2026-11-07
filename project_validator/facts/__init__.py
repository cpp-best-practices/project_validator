"""The fact database: what the extractors learned about a project, each fact with where it was found.

Facts are immutable records. Extractors (CI providers first; build systems, toolchains and tools later) record them;
questions query them (see docs/architecture.md). Nothing here judges a project.
"""

import dataclasses
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

type Location = tuple[str | int, ...]

NOTHING: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class Origin:
    """Where a fact was found: a file, and the place inside it (`("jobs", "test", "steps", 3, "run")`)."""

    path: str
    at: Location = ()

    def __str__(self) -> str:
        """`.github/workflows/ci.yml:jobs.test.steps[3].run`."""
        place = ""
        for part in self.at:
            place += f"[{part}]" if isinstance(part, int) else f".{part}" if place else part
        return f"{self.path}:{place}" if place else self.path


@dataclass(frozen=True, slots=True, kw_only=True)
class Fact:
    origin: Origin


@dataclass(frozen=True, slots=True, kw_only=True)
class CiJob(Fact):
    """One CI job as it runs: one combination of its matrix, on one runner.

    `id` is unique in the project and names the job in other facts. `heuristic` jobs come from configuration that is
    not parsed; their commands are unknown.
    """

    id: str
    provider: str
    name: str
    os: str
    matrix: Mapping[str, str] = NOTHING
    image: str | None = None
    env: Mapping[str, str] = NOTHING
    heuristic: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Command(Fact):
    """A command a CI job runs: its arguments as the shell splits them, after matrix values are substituted.

    `line` is the command as written. Arguments still holding an expression the validator cannot evaluate
    (`${{ secrets.TOKEN }}`) are kept as written.
    """

    job: str
    argv: tuple[str, ...]
    line: str
    env: Mapping[str, str] = NOTHING
    directory: str | None = None
    # The condition the step runs under (GitHub's `if:`), as written after matrix values are substituted.
    condition: str | None = None
    # The commands that ran this one in turn, outermost first (CI's `npm test`, then the package's test script).
    via: tuple[Origin, ...] = ()


_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
# Programs that run the command that follows them.
_WRAPPERS = frozenset({"sudo", "time", "nice", "env", "emcmake", "emmake", "scan-build", "xvfb-run", "catchsegv"})


def resolved(command: Command) -> tuple[str, ...]:
    """The command's arguments with the shell variables its environment defines (`$BUILD_TYPE`) put in place, and
    without the programs that only run the command that follows them (`sudo`, `emcmake`)."""

    def value(match: re.Match[str]) -> str:
        return command.env.get(match[1] or match[2], match[0])

    words = [_VARIABLE.sub(value, word) for word in command.argv]
    while len(words) > 1 and (words[0] in _WRAPPERS or (words[0] != command.argv[0] and "=" in words[0])):
        words = words[1:]
    return tuple(words)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionStep(Fact):
    """A reusable step a CI job runs, such as a GitHub action, with its inputs."""

    job: str
    uses: str
    inputs: Mapping[str, str] = NOTHING
    condition: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Unknown(Fact):
    """Something an extractor could not read, so that its absence is not taken for "no"."""

    subject: str
    reason: str


@dataclass(frozen=True, slots=True)
class Facts:
    """Every fact about one project, in the order the extractors recorded them."""

    all: tuple[Fact, ...] = field(default=())

    def of[F: Fact](self, kind: type[F]) -> tuple[F, ...]:
        return tuple(fact for fact in self.all if isinstance(fact, kind))

    def __iter__(self) -> Iterator[Fact]:
        return iter(self.all)

    def as_dicts(self) -> list[dict[str, object]]:
        return [as_dict(fact) for fact in self.all]


def as_dict(fact: Fact) -> dict[str, object]:
    """A fact as JSON-ready data: its kind, then its fields, with the origin written out."""
    data: dict[str, object] = {"kind": type(fact).__name__}
    for item in dataclasses.fields(fact):
        value = getattr(fact, item.name)
        data[item.name] = _plain(value)
    return data


def _plain(value: object) -> object:
    if isinstance(value, Origin):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_plain(item) for item in value)  # type: ignore[type-var]
    return value


def collected(groups: Iterable[Iterable[Fact]]) -> Facts:
    return Facts(tuple(fact for group in groups for fact in group))


__all__ = [
    "NOTHING",
    "ActionStep",
    "CiJob",
    "Command",
    "Fact",
    "Facts",
    "Origin",
    "Unknown",
    "as_dict",
    "collected",
    "resolved",
]
