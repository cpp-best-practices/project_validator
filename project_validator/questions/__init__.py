"""Questions: queries over the fact database, each answering one thing about the project per language.

Answers are the stable, machine-readable interface (`--answers`); checks judge them by a policy and never read
extractors (see docs/architecture.md).
"""

import enum


class Answer(enum.StrEnum):
    """`impossible`: no known tool can provide it for the language. `unknown`: something that could provide it was
    not read (see `project_validator.facts.Unknown`)."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    IMPOSSIBLE = "impossible"


__all__ = ["Answer"]
