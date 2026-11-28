"""What outside services say of the project (upstream #412), asked only with --ask-services: the OpenSSF Scorecard
score, and the latest version each package registry publishes beside the manifest's. Read from answers recorded from
the services, never the network."""

from __future__ import annotations

import json
import os
import unittest
from collections.abc import Mapping
from unittest import mock

from project_validator import hosting, services
from project_validator.about.services import outside_services
from project_validator.cli import _options, _parser
from project_validator.core import Options
from project_validator.facts import Fact, Facts
from project_validator.facts.history import PackageName
from project_validator.hosting import Refused
from project_validator.services import PublishedVersion, Scorecard, ServiceAccess, ServiceUnread, service_facts
from tests.support import FIXTURES, make_context, temp_project

ANSWERS = json.loads((FIXTURES / "online_answers.json").read_text(encoding="utf-8"))
SCORECARD = "https://api.securityscorecards.dev/projects/github.com/nlohmann/json"
PYPI = "https://pypi.org/pypi/requests/json"
CRATES = "https://crates.io/api/v1/crates/serde"
NPM = "https://registry.npmjs.org/left-pad/latest"
REMOTE = "git@github.com:nlohmann/json.git"
FILES = {
    "pyproject.toml": '[project]\nname = "requests"\nversion = "2.34.0"\n',
    "requests/__init__.py": "",
    "Cargo.toml": '[package]\nname = "serde"\nversion = "1.0.229"\n',
    "src/lib.rs": "",
    "package.json": json.dumps({"name": "left-pad", "version": "1.3.0"}),
    "index.js": "",
}


class _Service:
    """A fake `fetch`: each URL's answer (a `Refused` is raised; any other URL is a 404), and the headers sent."""

    def __init__(self, answers: Mapping[str, object]) -> None:
        self.answers = answers
        self.asked: dict[str, Mapping[str, str]] = {}

    def __call__(self, url: str, headers: Mapping[str, str]) -> object:
        self.asked[url] = headers
        answer = self.answers.get(url, Refused(404, "HTTP 404"))
        if isinstance(answer, Refused):
            raise answer
        return answer


RECORDED = {SCORECARD: ANSWERS["scorecard"], PYPI: ANSWERS["pypi"], CRATES: ANSWERS["crates"], NPM: ANSWERS["npm"]}


def _facts(files: Mapping[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _asked(
    files: Mapping[str, str], answers: Mapping[str, object], *, url: str | None = REMOTE, ask: bool = True
) -> tuple[list[Fact], _Service]:
    fake = _Service(answers)
    facts = _facts(files)
    environment = {key: value for key, value in os.environ.items() if key != hosting.OFFLINE_VARIABLE}
    with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(hosting, "fetch", fake):
        return list(service_facts(url, facts, ask=ask)), fake


def _one[T](facts: list[Fact], kind: type[T]) -> T:
    [found] = [fact for fact in facts if isinstance(fact, kind)]
    return found


def _shown(facts: list[Fact]) -> dict[str, str]:
    return {detail.subject: detail.text for detail in outside_services(Facts(facts))}


class PackageNameTests(unittest.TestCase):
    def test_a_manifest_names_its_package_unless_it_is_never_published(self) -> None:
        found = {package.origin.path: package.name for package in _facts(FILES).of(PackageName)}
        self.assertEqual(found, {"pyproject.toml": "requests", "Cargo.toml": "serde", "package.json": "left-pad"})
        unpublished = {
            "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\npublish = false\n',
            "src/main.rs": "",
            "package.json": json.dumps({"name": "site", "version": "1.0.0", "private": True}),
            "index.js": "",
        }
        self.assertEqual(_facts(unpublished).of(PackageName), ())


class AskedTests(unittest.TestCase):
    def test_without_the_option_nothing_is_asked(self) -> None:
        facts, fake = _asked(FILES, RECORDED, ask=False)
        self.assertEqual((facts, fake.asked), ([], {}))

    def test_offline_the_services_are_not_asked_and_it_says_so(self) -> None:
        with mock.patch.object(hosting, "fetch", side_effect=AssertionError("asked")):
            # The test suite runs offline (tests/__init__.py).
            facts = list(service_facts(REMOTE, _facts(FILES), ask=True))
        self.assertEqual(_one(facts, ServiceAccess).reason, "outside services are not asked offline (--offline)")
        self.assertEqual(list(service_facts(REMOTE, _facts(FILES), ask=True, requested_offline=True)), facts)

    def test_only_the_top_manifests_are_asked_of_and_each_call_names_the_validator(self) -> None:
        files = {**FILES, "sub/pyproject.toml": '[project]\nname = "sub"\nversion = "0.1.0"\n'}
        _facts_found, fake = _asked(files, RECORDED)
        self.assertEqual(sorted(fake.asked), sorted(RECORDED))
        self.assertTrue(all("project_validator" in headers["User-Agent"] for headers in fake.asked.values()))


class ScorecardTests(unittest.TestCase):
    def test_the_score_and_its_date(self) -> None:
        found = _one(_asked(FILES, RECORDED)[0], Scorecard)
        self.assertEqual((found.repository, found.score, found.date), ("github.com/nlohmann/json", 9.1, "2026-11-24"))

    def test_a_repository_scorecard_has_not_scored_or_can_not_score_says_so(self) -> None:
        unscored = _asked(FILES, {})[0]
        self.assertEqual(
            _one(unscored, ServiceUnread).reason,
            "Scorecard has no score for github.com/nlohmann/json (HTTP 404)",
        )
        elsewhere = _asked({"README.md": ""}, {}, url="git@example.org:o/r.git")[0]
        self.assertEqual(_one(elsewhere, ServiceUnread).reason, "Scorecard does not score example.org")
        nowhere = _asked({"README.md": ""}, {}, url=None)[0]
        self.assertEqual(_one(nowhere, ServiceUnread).reason, "the project has no origin remote on a host")


class RegistryTests(unittest.TestCase):
    def test_each_registry_says_its_latest_version(self) -> None:
        found = {fact.registry: fact for fact in _asked(FILES, RECORDED)[0] if isinstance(fact, PublishedVersion)}
        self.assertEqual(
            {name: (fact.package, fact.manifest, fact.version, fact.published) for name, fact in found.items()},
            {
                "PyPI": ("requests", "pyproject.toml", "2.34.0", "2.34.2"),
                "crates.io": ("serde", "Cargo.toml", "1.0.229", "1.0.229"),
                "npm": ("left-pad", "package.json", "1.3.0", "1.3.0"),
            },
        )

    def test_a_package_the_registry_does_not_have_is_not_published(self) -> None:
        found = _asked(FILES, {**RECORDED, PYPI: Refused(404, "HTTP 404", "Not Found")})[0]
        pypi = [fact for fact in found if isinstance(fact, PublishedVersion) and fact.registry == "PyPI"]
        self.assertEqual([fact.published for fact in pypi], [None])

    def test_a_registry_that_does_not_answer_says_so(self) -> None:
        found = _asked(FILES, {**RECORDED, CRATES: Refused(0, "timed out")})[0]
        self.assertEqual(
            [(fact.service, fact.subject, fact.reason) for fact in found if isinstance(fact, ServiceUnread)],
            [("crates.io", "serde", "crates.io did not answer (timed out)")],
        )

    def test_a_package_whose_manifest_says_no_version_is_still_asked_of(self) -> None:
        files = {"pyproject.toml": '[project]\nname = "requests"\ndynamic = ["version"]\n', "requests/__init__.py": ""}
        found = _asked(files, RECORDED)[0]
        self.assertEqual(_shown(found)["PyPI requests"], "2.34.2 is published; pyproject.toml says no version")

    def test_a_scoped_npm_package_keeps_its_scope(self) -> None:
        files = {"package.json": json.dumps({"name": "@scope/pad", "version": "1.0.0"}), "index.js": ""}
        _found, fake = _asked(files, {})
        self.assertIn("https://registry.npmjs.org/@scope/pad/latest", fake.asked)


class ShownTests(unittest.TestCase):
    def test_each_service_is_shown_in_words(self) -> None:
        found = _asked(FILES, {**RECORDED, NPM: Refused(404, "HTTP 404"), CRATES: Refused(503, "HTTP 503")})[0]
        self.assertEqual(
            _shown(found),
            {
                "OpenSSF Scorecard": "github.com/nlohmann/json scores 9.1 of 10 (on 2026-11-24)",
                "PyPI requests": "2.34.2 is published; pyproject.toml says 2.34.0",
                "crates.io serde": "not read: crates.io did not answer (HTTP 503)",
                "npm left-pad": "not published on npm (package.json says 1.3.0)",
            },
        )

    def test_a_version_the_registry_publishes_says_so(self) -> None:
        shown = _shown(_asked(FILES, RECORDED)[0])
        self.assertEqual(shown["crates.io serde"], "1.0.229 is published, the version Cargo.toml says")

    def test_offline_says_the_services_were_not_asked(self) -> None:
        facts = list(service_facts(REMOTE, _facts(FILES), ask=True))
        self.assertEqual(
            _shown(facts), {"outside services": "not read: outside services are not asked offline (--offline)"}
        )


class OptionTests(unittest.TestCase):
    def test_the_option_reaches_the_options_and_is_off_by_default(self) -> None:
        self.assertFalse(Options().ask_services)
        self.assertTrue(_options(_parser().parse_args(["--ask-services"])).ask_services)

    def test_the_analysis_asks_the_services_only_with_the_option(self) -> None:
        with (
            temp_project(FILES) as root,
            mock.patch.object(services, "service_facts", return_value=iter(())) as asked,
        ):
            _ = make_context(root, Options(ask_services=True)).facts
        self.assertTrue(asked.call_args.kwargs["ask"])


if __name__ == "__main__":
    unittest.main()
