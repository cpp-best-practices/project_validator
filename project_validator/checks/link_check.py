"""CI checks each documentation site's links and fails on a broken one: lychee (or its action) on the sources,
Sphinx's `linkcheck` builder, markdown-link-check, mdbook-linkcheck, linkinator or muffet on the served site, htmltest
or HTMLProofer on the built one. A scheduled run counts: links rot without a change to the repository."""

from __future__ import annotations

from project_validator.facts.links import LINKS
from project_validator.judging import answered_check
from project_validator.policy.links import judge_link_check
from project_validator.questions.links import link_check as link_answers

link_check = answered_check(
    name="link-check",
    description="CI checks each documentation site's links in each unit and fails on a broken one (lychee, "
    "sphinx-build -b linkcheck, markdown-link-check, mdbook-linkcheck, linkinator, muffet, htmltest, HTMLProofer); a "
    "scheduled run counts. Warns otherwise",
    aspect=LINKS,
    answers=link_answers,
    judge=judge_link_check,
)
