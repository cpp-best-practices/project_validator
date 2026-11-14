"""The link aspect of tools (see `project_validator.facts.tools`): a run checks the links of a documentation site and
fails on a broken one (`links`: lychee on the Markdown sources, Sphinx's `linkcheck` builder, markdown-link-check,
mdbook-linkcheck, linkinator or muffet on the served site, htmltest or HTMLProofer on the built one, LinkChecker). All
are ordinary `Tool`s; `link_checker` and `links_checked` only spell them."""

from __future__ import annotations

from collections.abc import Iterable

from project_validator.facts import Setting
from project_validator.facts.tools import Claim, Run, Tool, provided

LINKS = "links"
CHECKED = "checked"


def link_checker(*, name: str, languages: frozenset[str], how: str, checks: Claim, reads: tuple[str, ...] = ()) -> Tool:
    """A checker of the links of the documentation of `languages` (the generators' formats): `how` to run it."""
    return Tool(name=name, languages=languages, can={LINKS: {CHECKED: how}}, claims=checks, reads=reads)


def links_checked(*, read: Iterable[Setting | str] = (), heuristic: bool = False) -> Run:
    return provided(LINKS, CHECKED, read=read, heuristic=heuristic)


__all__ = ["CHECKED", "LINKS", "link_checker", "links_checked"]
