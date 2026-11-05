import re
import unittest
from collections.abc import Mapping

from project_validator.checks.security_policy import HINT, security_policy
from project_validator.core import Result, Status
from project_validator.evidence import documents
from tests.support import FIXTURES, make_context, temp_project


def _run(files: Mapping[str, str]) -> Result:
    with temp_project(files) as root:
        return security_policy.run(make_context(root))


class SecurityPolicyTests(unittest.TestCase):
    def test_applies_to_every_language(self) -> None:
        self.assertEqual(security_policy.languages, frozenset())

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = security_policy.run(make_context(FIXTURES / "well_configured"))
        self.assertEqual(result, Result.passed("SECURITY.md says how to report a vulnerability"))

    def test_warns_without_a_security_policy(self) -> None:
        for files in ({}, {"src/SECURITY.md": "mail security@example.com"}):
            with self.subTest(files=list(files)):
                self.assertEqual(_run(files), Result.warned("no security policy", HINT))

    def test_a_policy_says_how_to_report(self) -> None:
        ways = {
            "an email address": "Mail security@example.org.",
            "a link": "Use https://example.com/report.",
            "private vulnerability reporting": "Use GitHub's Private Vulnerability Reporting.",
            "security advisories": "Open a draft security advisory.",
        }
        for way, text in ways.items():
            with self.subTest(way):
                self.assertEqual(_run({"SECURITY.md": text}).status, Status.PASS)

    def test_a_policy_is_found_where_forges_look_for_it(self) -> None:
        for path in ("SECURITY.md", "security.rst", ".github/SECURITY.md", "docs/SECURITY.txt", "SECURITY"):
            with self.subTest(path):
                result = _run({path: "security@example.com"})
                self.assertEqual(result, Result.passed(f"{path} says how to report a vulnerability"))

    def test_warns_when_the_policy_does_not_say_how_to_report(self) -> None:
        result = _run({"SECURITY.md": "We take security seriously.\n"})
        self.assertEqual(result, Result.warned("SECURITY.md does not say how to report a vulnerability", HINT))
        result = _run({"SECURITY.md": "Nothing here.", ".github/SECURITY.md": "security@example.com"})
        self.assertEqual(result.message, ".github/SECURITY.md says how to report a vulnerability")


class DocumentsTests(unittest.TestCase):
    def test_finds_documents_in_order_of_their_directories(self) -> None:
        files = {"docs/NOTES.md": "", ".github/notes": "", "notes.txt": "", "src/notes.md": "", "docs/notes/x": ""}
        with temp_project(files) as root:
            found = documents(make_context(root), re.compile(r"notes(?:\.\w+)?", re.IGNORECASE))
        self.assertEqual(found, ["notes.txt", ".github/notes", "docs/NOTES.md"])
