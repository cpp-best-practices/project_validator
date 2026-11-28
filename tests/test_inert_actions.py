"""The curated list of actions known to run none of the project's code (upstream #273) stays easy to read and to add
to: grouped by what the actions do, sorted, lower case, each listed once, and none that the validator models as running
commands."""

from __future__ import annotations

import re
import unittest

from project_validator.ci.inert_actions import INERT_ACTIONS, inert
from project_validator.facts.expansion import known_actions

_ENTRY = re.compile(r"^[a-z0-9_.-]+/[a-z0-9_.-]+(?:/[a-z0-9_./-]+)?$")


class CuratedListTests(unittest.TestCase):
    def test_each_group_is_sorted_lower_case_and_well_formed(self) -> None:
        for group in INERT_ACTIONS:
            with self.subTest(group=group.does):
                self.assertEqual(list(group.actions), sorted(group.actions))
                self.assertEqual([entry for entry in group.actions if not _ENTRY.match(entry)], [])

    def test_each_action_is_listed_once(self) -> None:
        entries = [entry for group in INERT_ACTIONS for entry in group.actions]
        self.assertEqual(sorted({entry for entry in entries if entries.count(entry) > 1}), [])

    def test_no_listed_action_is_modelled_as_running_commands(self) -> None:
        modelled = {action.name.lower() for action in known_actions()}
        listed = {entry for group in INERT_ACTIONS for entry in group.actions}
        self.assertEqual(sorted(listed & modelled), [])

    def test_an_entry_covers_the_actions_under_its_path_and_github_s_own(self) -> None:
        self.assertTrue(inert("mitchellh/vouch/action/check-pr"))
        self.assertTrue(inert("Step-Security/Harden-Runner"))
        self.assertTrue(inert("actions/checkout"))
        self.assertFalse(inert("mitchellh/vouchers"))  # a prefix of a name is not its path
        self.assertFalse(inert("actions-ecosystem/action-add-labels"))  # GitHub's own are `actions/`, not `actions-`
        self.assertFalse(inert("crate-ci/typos"))  # it spell-checks the project


if __name__ == "__main__":
    unittest.main()
