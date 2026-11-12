"""What every built-in ecosystem promises: a project that follows its practices passes, and a bare one does not.

Adding an ecosystem means adding its profile and these two fixtures, named after the profile's module; no check
needs to change.
"""

from __future__ import annotations

import unittest

from project_validator.core import Status
from project_validator.ecosystems import PROFILES, Ecosystem, applies_to, ecosystems_for, registered
from project_validator.plugins import discover
from project_validator.runner import run_checks
from tests.support import FIXTURES, make_context

# Ecosystem -> (a project that follows all of its practices, a project that follows none of them), named after the
# profile's module.
FIXTURES_OF = {ecosystem: (f"well_configured_{name}", f"bare_{name}") for name, ecosystem in PROFILES.items()}


def _statuses(fixture: str) -> dict[str, tuple[Status, str]]:
    context = make_context(FIXTURES / fixture)
    return {
        report.check.name: (report.result.status, report.result.message)
        for report in run_checks(discover().checks, context)
    }


def _judges(ecosystem: Ecosystem) -> dict[str, bool]:
    """Check name -> whether it judges `ecosystem` specifically (rather than every project)."""
    return {check.name: ecosystem.label in applies_to(check) for check in discover().checks if applies_to(check)}


def _applying(fixture: str) -> set[str]:
    """The checks that apply to the fixture: those of every project, and those of an ecosystem the fixture uses (its
    own, and the formats its data files are in: every project has some)."""
    structure = make_context(FIXTURES / fixture).structure
    used = {ecosystem.label for ecosystem in ecosystems_for(structure.languages_and_formats, registered())}
    return {check.name for check in discover().checks if not applies_to(check) or set(applies_to(check)) & used}


class EcosystemContractTests(unittest.TestCase):
    def test_every_built_in_ecosystem_has_fixtures(self) -> None:
        for fixtures in FIXTURES_OF.values():
            for fixture in fixtures:
                self.assertTrue((FIXTURES / fixture).is_dir(), fixture)

    def test_fixtures_are_recognised_as_their_ecosystem(self) -> None:
        """A language ecosystem's fixtures are written in its languages alone; a format ecosystem's are in its
        formats (beside those of their CI configuration) and in no language."""
        for ecosystem, fixtures in FIXTURES_OF.items():
            for fixture in fixtures:
                with self.subTest(fixture=fixture):
                    structure = make_context(FIXTURES / fixture).structure
                    if ecosystem.kind == "language":
                        self.assertTrue(structure.languages)
                        self.assertLessEqual(structure.languages, ecosystem.languages)
                    else:
                        self.assertTrue(structure.formats & ecosystem.languages)
                        self.assertEqual(structure.languages, frozenset())

    def test_a_well_configured_project_passes_every_check_that_applies_to_it(self) -> None:
        for ecosystem, (well_configured, _) in FIXTURES_OF.items():
            applying = _applying(well_configured)
            for name, (status, message) in _statuses(well_configured).items():
                with self.subTest(ecosystem=ecosystem.label, check=name):
                    expected = Status.PASS if name in applying else Status.SKIP
                    self.assertEqual(status, expected, message)

    def test_a_bare_project_passes_none_of_its_ecosystems_practices(self) -> None:
        for ecosystem, (_, bare) in FIXTURES_OF.items():
            judges = _judges(ecosystem)
            for name, (status, message) in _statuses(bare).items():
                if judges.get(name):
                    with self.subTest(ecosystem=ecosystem.label, check=name):
                        self.assertIn(status, (Status.WARN, Status.FAIL), message)
