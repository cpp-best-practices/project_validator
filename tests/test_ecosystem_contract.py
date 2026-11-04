"""What every built-in ecosystem promises: a project that follows its practices passes, and a bare one does not.

Adding an ecosystem means adding its profile and these two fixtures; no check needs to change.
"""

import unittest

from project_validator.core import Status
from project_validator.ecosystems import BUILT_IN, C_AND_CXX, GO, PYTHON, RUST, Ecosystem, applies_to
from project_validator.plugins import discover
from project_validator.runner import run_checks
from tests.support import FIXTURES, make_context

# Ecosystem -> (a project that follows all of its practices, a project that follows none of them).
FIXTURES_OF = {
    C_AND_CXX: ("well_configured", "bare_project"),
    PYTHON: ("well_configured_python", "bare_python"),
    RUST: ("well_configured_rust", "bare_rust"),
    GO: ("well_configured_go", "bare_go"),
}


def _statuses(fixture: str) -> dict[str, tuple[Status, str]]:
    context = make_context(FIXTURES / fixture)
    return {
        report.check.name: (report.result.status, report.result.message)
        for report in run_checks(discover().checks, context)
    }


def _judges(ecosystem: Ecosystem) -> dict[str, bool]:
    """Check name -> whether it judges `ecosystem` specifically (rather than every project)."""
    return {check.name: ecosystem.label in applies_to(check) for check in discover().checks if applies_to(check)}


class EcosystemContractTests(unittest.TestCase):
    def test_every_built_in_ecosystem_has_fixtures(self) -> None:
        self.assertEqual(set(FIXTURES_OF), set(BUILT_IN))
        for fixtures in FIXTURES_OF.values():
            for fixture in fixtures:
                self.assertTrue((FIXTURES / fixture).is_dir(), fixture)

    def test_fixtures_are_recognised_as_their_ecosystem(self) -> None:
        for ecosystem, fixtures in FIXTURES_OF.items():
            for fixture in fixtures:
                with self.subTest(fixture=fixture):
                    languages = make_context(FIXTURES / fixture).structure.languages
                    self.assertTrue(languages)
                    self.assertLessEqual(languages, ecosystem.languages)

    def test_a_well_configured_project_passes_every_check_that_applies_to_it(self) -> None:
        for ecosystem, (well_configured, _) in FIXTURES_OF.items():
            judges = _judges(ecosystem)
            for name, (status, message) in _statuses(well_configured).items():
                with self.subTest(ecosystem=ecosystem.label, check=name):
                    expected = Status.SKIP if judges.get(name) is False else Status.PASS
                    self.assertEqual(status, expected, message)

    def test_a_bare_project_passes_none_of_its_ecosystems_practices(self) -> None:
        for ecosystem, (_, bare) in FIXTURES_OF.items():
            judges = _judges(ecosystem)
            for name, (status, message) in _statuses(bare).items():
                if judges.get(name):
                    with self.subTest(ecosystem=ecosystem.label, check=name):
                        self.assertIn(status, (Status.WARN, Status.FAIL), message)
