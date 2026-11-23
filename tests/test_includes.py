"""The shared include follower: cycles, the depth limit, files the project does not hold, and provenance."""

from __future__ import annotations

import unittest

from project_validator.includes import Chain, Refused, follow
from project_validator.limits import Limit

LIMIT = Limit("its includes", 2)
FILES = frozenset({"a.mk", "b.mk", "c.mk"})


def _follow(chain: Chain, path: str) -> Chain | Refused:
    return follow(chain, path, LIMIT, FILES.__contains__)


class FollowTests(unittest.TestCase):
    def test_a_file_followed_extends_the_chain_that_reached_it(self) -> None:
        chain = _follow(Chain.start("Makefile"), "a.mk")
        self.assertEqual(chain, Chain(("Makefile", "a.mk")))
        self.assertEqual(str(chain), "Makefile → a.mk")

    def test_a_file_already_in_the_chain_is_a_cycle(self) -> None:
        chain = Chain(("Makefile", "a.mk"))
        self.assertEqual(_follow(chain, "Makefile"), Refused("Makefile includes itself, through Makefile → a.mk"))

    def test_a_cycle_says_how_the_file_is_followed(self) -> None:
        """A reusable workflow calls, an action uses: the reader names the link, for the reason to read true."""
        refused = follow(Chain(("ci.yml", "w.yml")), "w.yml", LIMIT, verb="calls")
        self.assertEqual(refused, Refused("w.yml calls itself, through ci.yml → w.yml"))

    def test_a_reader_whose_loader_says_what_is_missing_need_not_ask_whether_a_file_exists(self) -> None:
        self.assertEqual(follow(Chain.start("ci.yml"), "w.yml", LIMIT), Chain(("ci.yml", "w.yml")))

    def test_the_chain_is_followed_at_most_the_limit_deep(self) -> None:
        at = _follow(Chain(("Makefile", "a.mk")), "b.mk")
        self.assertEqual(at, Chain(("Makefile", "a.mk", "b.mk")))
        self.assertEqual(_follow(at, "c.mk"), Refused(LIMIT.reason))  # type: ignore[arg-type]

    def test_a_file_the_project_does_not_hold_is_refused_with_why(self) -> None:
        refused = _follow(Chain.start("Makefile"), "gen.mk")
        self.assertEqual(refused, Refused("gen.mk is not in the project", missing=True))


if __name__ == "__main__":
    unittest.main()
