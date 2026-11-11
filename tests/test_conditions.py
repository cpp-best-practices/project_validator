from __future__ import annotations

import unittest
from unittest import mock

from project_validator.facts import conditions
from project_validator.facts.build import Applies, disjuncts
from project_validator.facts.conditions import (
    ALWAYS,
    DIMENSIONS,
    NEVER,
    both,
    either,
    negated,
    only,
    paths,
    requiring,
)

MSVC = only("compilers", ["msvc"])
LINUX = only("platforms", ["linux"])
OPTION = requiring("ENABLE_X")


class ConditionTests(unittest.TestCase):
    def test_conditions_are_equal_when_they_hold_in_the_same_builds(self) -> None:
        self.assertEqual(either(MSVC, negated(MSVC)), ALWAYS)
        self.assertEqual(both(MSVC, negated(MSVC)), NEVER)
        self.assertEqual(negated(negated(both(MSVC, OPTION))), both(OPTION, MSVC))
        self.assertEqual(either(both(OPTION, MSVC), both(negated(OPTION), MSVC)), MSVC)

    def test_a_condition_is_true_when_it_holds_in_some_build(self) -> None:
        self.assertTrue(MSVC)
        self.assertFalse(both(MSVC, only("compilers", ["gcc"])))

    def test_every_value_or_none_of_a_dimension(self) -> None:
        self.assertEqual(only("compilers", DIMENSIONS["compilers"]), ALWAYS)
        self.assertEqual(only("compilers", []), NEVER)

    def test_long_chains_of_branches_stay_small(self) -> None:
        remaining = ALWAYS
        for index in range(200):
            remaining = both(remaining, negated(requiring(f"OPTION_{index}")))
        self.assertTrue(remaining)
        self.assertEqual(len(paths(remaining)), 1)

    def test_paths_are_capped(self) -> None:
        many = either(*(both(requiring(f"A{index}"), requiring(f"B{index}")) for index in range(10)))
        with mock.patch.object(conditions, "MOST_DISJUNCTS", 3):
            self.assertEqual(len(paths(many)), 3)


class DisjunctTests(unittest.TestCase):
    def test_a_condition_is_written_out_as_few_disjuncts(self) -> None:
        self.assertEqual(disjuncts(ALWAYS), (Applies(),))
        self.assertEqual(disjuncts(NEVER), ())
        self.assertEqual(disjuncts(negated(MSVC)), (Applies(compilers=frozenset(DIMENSIONS["compilers"]) - {"msvc"}),))
        self.assertEqual(
            disjuncts(both(MSVC, negated(OPTION))),
            (Applies(compilers=frozenset({"msvc"}), requires=frozenset({"NOT ENABLE_X"})),),
        )

    def test_disjuncts_that_differ_in_one_dimension_are_merged(self) -> None:
        gcc_or_clang = either(only("compilers", ["gcc"]), only("compilers", ["clang"]))
        [found] = disjuncts(both(gcc_or_clang, LINUX))
        self.assertEqual(found, Applies(compilers=frozenset({"gcc", "clang"}), platforms=frozenset({"linux"})))

    def test_paths_that_differ_in_one_dimension_are_merged(self) -> None:
        windows = only("platforms", ["windows"])
        gcc = only("compilers", ["gcc"])
        found = disjuncts(either(both(MSVC, LINUX, OPTION), both(gcc, either(both(LINUX, OPTION), windows))))
        merged = Applies(
            compilers=frozenset({"msvc", "gcc"}), platforms=frozenset({"linux"}), requires=frozenset({"ENABLE_X"})
        )
        self.assertEqual(set(found), {merged, Applies(compilers=frozenset({"gcc"}), platforms=frozenset({"windows"}))})
        self.assertEqual(
            disjuncts(either(both(MSVC, OPTION), both(negated(MSVC), OPTION))),
            (Applies(requires=frozenset({"ENABLE_X"})),),
        )

    def test_disjuncts_that_differ_in_more_stay_apart(self) -> None:
        self.assertEqual(len(disjuncts(either(both(MSVC, OPTION), LINUX))), 2)
        self.assertEqual(
            len(disjuncts(either(both(MSVC, LINUX), both(only("compilers", ["gcc"]), only("platforms", ["windows"]))))),
            2,
        )
        self.assertEqual(
            len(disjuncts(either(both(MSVC, OPTION), both(only("compilers", ["gcc"]), requiring("B"))))), 2
        )

    def test_what_an_applies_allows(self) -> None:
        applies = Applies(compilers=frozenset({"gcc"}), requires=frozenset({"X"}))
        self.assertEqual(applies.allowed("compilers"), {"gcc"})
        self.assertEqual(applies.allowed("platforms"), set(DIMENSIONS["platforms"]))
        self.assertFalse(applies.unconditional)
        self.assertTrue(Applies().unconditional)


class DimensionTests(unittest.TestCase):
    def test_identifiers_name_values(self) -> None:
        compilers = conditions.Dimension("compilers", {"GNU": "gcc", "Clang": ("clang", "appleclang")})
        self.assertEqual(compilers.equal_to("Clang"), only("compilers", ["clang", "appleclang"]))
        self.assertEqual(compilers.equal_to("Unheard"), only("compilers", ["other"]))
        insensitive = conditions.Dimension("configurations", {"Debug": "debug"}, case_sensitive=False)
        self.assertEqual(insensitive.listed(["debug", "x"]), only("configurations", ["debug", "other"]))


class OpenDimensionTests(unittest.TestCase):
    """A value a condition names joins its dimension; conditions made before hold for it as for "other"."""

    def setUp(self) -> None:
        saved = list(conditions.DIMENSIONS["compilers"])
        self.addCleanup(lambda: conditions._VALUES["compilers"].__setitem__(slice(None), saved))

    def test_a_value_named_later_branches_as_other_did(self) -> None:
        not_msvc = negated(only("compilers", ["msvc"]))
        others = only("compilers", ["other"])
        with self.assertRaises(ValueError):
            only("compilers", ["zcc-for-a-test"])
        conditions.extend("compilers", "zcc-for-a-test", "zcc-for-a-test")
        zcc = only("compilers", ["zcc-for-a-test"])
        self.assertIn("zcc-for-a-test", DIMENSIONS["compilers"])
        self.assertEqual(len(DIMENSIONS), 4)
        self.assertEqual(both(not_msvc, zcc), zcc)
        # "other" named before meant every compiler not named yet; named after, it no longer covers zcc.
        self.assertEqual(both(others, zcc), zcc)
        self.assertEqual(both(only("compilers", ["other"]), zcc), NEVER)
        # A condition made before and one made after the value was named are the same.
        self.assertEqual(negated(negated(not_msvc)), not_msvc)
        self.assertEqual(either(not_msvc, only("compilers", ["msvc"])), ALWAYS)
        allowed = {applies.compilers for applies in disjuncts(both(not_msvc, zcc))}
        self.assertEqual(allowed, {frozenset({"zcc-for-a-test"})})
