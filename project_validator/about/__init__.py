"""What the validator shows of a project without judging it (upstream #412): context for the checks, in the views'
"About the project" section and under `about` in the JSON. Nothing here counts towards a result or the score; an
item may become a check once the corpus shows where to draw a line.

Each group reads the facts alone, so the details are reproducible offline: the same checkout says the same thing.
A group is a function of the facts that yields `Detail`s, in a module of its own; `GROUPS` lists them in the order
they are shown.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from project_validator.about.ci import ci_shape, tools
from project_validator.about.dependencies import dependencies
from project_validator.about.detail import Detail
from project_validator.about.documents import documents
from project_validator.about.history import history
from project_validator.about.licences import licences
from project_validator.about.publishing import publishing
from project_validator.about.size import size
from project_validator.about.versions import versions
from project_validator.facts import Facts

# The groups shown, in order: each a function of the facts.
GROUPS: tuple[Callable[[Facts], Iterable[Detail]], ...] = (
    versions,
    size,
    dependencies,
    licences,
    history,
    tools,
    ci_shape,
    publishing,
    documents,
)


def about(facts: Facts) -> tuple[Detail, ...]:
    """Everything shown about the project, group by group."""
    return tuple(detail for group in GROUPS for detail in group(facts))


__all__ = ["GROUPS", "Detail", "about"]
