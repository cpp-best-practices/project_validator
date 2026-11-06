"""The coverage aspect of tools (see `project_validator.facts.tools`): its levels, the granularities of coverage.

Coverage tools are ordinary `Tool`s whose `can` holds a `coverage` aspect; their runs are `ToolRun`s that provide
it. `coverage_tool` and `measured` only spell those for coverage.
"""

import enum
from collections.abc import Iterable, Mapping

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Run, Tool, provided

COVERAGE = "coverage"


class Granularity(enum.StrEnum):
    """What a coverage measurement counts, from coarsest to finest.

    `path` stands for the coverage of combinations of decisions: path, prime path, condition and MC/DC coverage.
    """

    LINE = "line"
    STATEMENT = "statement"
    REGION = "region"
    BRANCH = "branch"
    PATH = "path"

    @property
    def rank(self) -> int:
        return tuple(Granularity).index(self)


def coverage_tool(
    *,
    name: str,
    languages: frozenset[str],
    can: Mapping[Granularity, str],
    measures: Claim,
    reads: tuple[str, ...] = (),
) -> Tool:
    """A tool that measures coverage: `can` maps each granularity it measures to how to ask for it."""
    return Tool(
        name=name,
        languages=languages,
        can={COVERAGE: {str(granularity): how for granularity, how in can.items()}},
        claims=measures,
        reads=reads,
    )


def measured(*granularities: Granularity | None, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    """A run that measures the `granularities` that are not None."""
    return provided(COVERAGE, *granularities, read=read, heuristic=heuristic)


__all__ = ["COVERAGE", "Granularity", "coverage_tool", "measured"]
