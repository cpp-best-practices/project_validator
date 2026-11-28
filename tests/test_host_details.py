"""What the source-control host says of the repository beyond its settings (upstream #412): its metadata, activity,
security alerts, latest release and default-branch CI, read from answers recorded from GitHub, never the network."""

from __future__ import annotations

import copy
import io
import json
import os
import unittest
import urllib.error
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
from unittest import mock

from project_validator import host_details, hosting
from project_validator.about.host import host
from project_validator.facts import Fact, Facts, Origin
from project_validator.host_details import (
    HostActivity,
    HostCi,
    HostRelease,
    HostRepository,
    HostSecurity,
    HostUnread,
    github_details,
)
from project_validator.hosting import HostAccess, Refused, host_facts
from tests.support import FIXTURES

ANSWERS = json.loads((FIXTURES / "online_answers.json").read_text(encoding="utf-8"))
REPOSITORY = "https://api.github.com/repos/nlohmann/json"
GRAPHQL = "https://api.github.com/graphql"
# The day the answers were recorded: their windows are counted back from it.
RECORDED = datetime(2026, 11, 28, tzinfo=UTC)
ORIGIN = Origin(path=".git/config")


def _refused(recorded: Mapping[str, object]) -> Refused:
    return Refused(int(str(recorded["status"])), f"HTTP {recorded['status']}", str(recorded["message"]))


def _github(**changes: object) -> dict[str, object]:
    """The recorded answers of each URL GitHub was asked, with `changes` (a URL's answer, by its key below)."""
    answers: dict[str, object] = {
        REPOSITORY: ANSWERS["github_repository"],
        f"{REPOSITORY}/rules/branches/develop": [],
        GRAPHQL: ANSWERS["github_graphql"],
        f"{REPOSITORY}/dependabot/alerts?state=open&per_page=100": _refused(ANSWERS["dependabot_refused"]),
        f"{REPOSITORY}/code-scanning/alerts?state=open&per_page=100": ANSWERS["code_scanning_alerts"],
        f"{REPOSITORY}/private-vulnerability-reporting": ANSWERS["private_vulnerability_reporting"],
    }
    keys = {"graphql": GRAPHQL, "dependabot": f"{REPOSITORY}/dependabot/alerts?state=open&per_page=100"}
    answers |= {keys[key]: answer for key, answer in changes.items()}
    return answers


class _Host:
    """A fake `fetch`: each URL's answer (a `Refused` is raised; any other URL is a 404), and what was asked."""

    def __init__(self, answers: Mapping[str, object]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, object]] = []

    def __call__(self, url: str, headers: Mapping[str, str], body: Mapping[str, object] | None = None) -> object:
        del headers
        self.asked.append((url, body))
        answer = self.answers.get(url, Refused(404, "HTTP 404"))
        if isinstance(answer, Refused):
            raise answer
        return answer


def _asked(answers: Mapping[str, object], url: str = "git@github.com:nlohmann/json.git") -> tuple[list[Fact], _Host]:
    """The facts `host_facts` gives online, with a token, and the fake host that answered."""
    fake = _Host(answers)
    environment = {key: value for key, value in os.environ.items() if key != hosting.OFFLINE_VARIABLE}
    details: dict[str, hosting.Details] = {**host_details.DETAILS, "GitHub": partial(github_details, now=RECORDED)}
    with (
        mock.patch.dict(os.environ, {**environment, "GH_TOKEN": "t", "GITLAB_TOKEN": "t"}, clear=True),
        mock.patch.object(hosting, "fetch", fake),
        mock.patch.object(hosting, "_gh_token", return_value=None),
    ):
        return list(host_facts(url, details=details)), fake


def _one[T](facts: Sequence[object], kind: type[T]) -> T:
    [found] = [fact for fact in facts if isinstance(fact, kind)]
    return found


def _unread(facts: Sequence[object]) -> dict[str, str]:
    return {fact.item: fact.reason for fact in facts if isinstance(fact, HostUnread)}


class ClientTests(unittest.TestCase):
    def test_each_address_is_asked_once_in_a_run(self) -> None:
        _facts, fake = _asked(_github())
        urls = [url for url, _body in fake.asked]
        self.assertEqual(len(urls), len(set(urls)), urls)
        self.assertEqual(urls.count(REPOSITORY), 1)
        # The settings' three, then one GraphQL query and three REST calls for the security alerts and reporting.
        self.assertEqual(len(urls), 7)

    def test_the_graphql_query_is_posted_with_its_variables(self) -> None:
        _facts, fake = _asked(_github())
        [body] = [body for url, body in fake.asked if url == GRAPHQL]
        if not isinstance(body, dict):
            self.fail(f"no query was posted: {body!r}")
        self.assertEqual(body["variables"]["owner"], "nlohmann")
        self.assertEqual(body["variables"]["name"], "json")
        self.assertEqual(body["variables"]["stale"], "repo:nlohmann/json is:pr is:open updated:<2026-10-29")

    def test_a_refusal_keeps_the_hosts_message(self) -> None:
        error = Refused(403, "HTTP 403", "Resource not accessible by integration")
        self.assertEqual((str(error), error.detail), ("HTTP 403", "Resource not accessible by integration"))
        self.assertEqual(Refused(0, "timed out").detail, "")

    def test_fetch_posts_a_json_body_and_keeps_an_errors_message(self) -> None:
        answer = mock.MagicMock()
        answer.__enter__.return_value.read.return_value = b'{"data": {}}'
        with mock.patch("urllib.request.urlopen", return_value=answer) as opened:
            self.assertEqual(hosting.fetch(GRAPHQL, {"Accept": "a"}, {"query": "q"}), {"data": {}})
        request = opened.call_args.args[0]
        self.assertEqual((request.data, request.get_header("Content-type")), (b'{"query": "q"}', "application/json"))
        for body, detail in ((b'{"message": "Bad credentials"}', "Bad credentials"), (b"<html>", ""), (b"[]", "")):
            error = urllib.error.HTTPError(GRAPHQL, 401, "Unauthorized", mock.MagicMock(), io.BytesIO(body))
            self.addCleanup(error.close)
            with (
                self.subTest(body=body),
                mock.patch("urllib.request.urlopen", side_effect=error),
                self.assertRaises(Refused) as raised,
            ):
                hosting.fetch(GRAPHQL, {})
            self.assertEqual((raised.exception.status, raised.exception.detail), (401, detail))

    def test_offline_nothing_more_is_asked(self) -> None:
        with mock.patch.object(hosting, "fetch", side_effect=AssertionError("asked")):
            facts = list(host_facts("git@github.com:o/r.git", details=host_details.DETAILS))
        self.assertIsInstance(_one(facts, HostAccess), HostAccess)
        self.assertEqual(len(facts), 1)


class GitHubTests(unittest.TestCase):
    def test_the_repository_metadata_comes_from_the_settings_answer(self) -> None:
        found = _one(_asked(_github())[0], HostRepository)
        self.assertEqual(
            (found.archived, found.fork, found.visibility, found.homepage, found.licence),
            (False, False, "public", "https://json.nlohmann.me", "MIT"),
        )
        self.assertEqual(found.topics, ("bson", "cbor", "header-only", "json", "json-diff"))

    def test_activity_counts_open_items_and_the_median_time_to_close_in_the_window(self) -> None:
        found = _one(_asked(_github())[0], HostActivity)
        self.assertEqual((found.open_issues, found.open_pull_requests, found.stale_pull_requests), (19, 29, 0))
        # The issue closed in 2025 is outside the 90 days before the run.
        self.assertEqual((found.issues_closed, found.pull_requests_merged), (6, 5))
        self.assertEqual((found.days_to_close, found.days_to_merge), (3.6, 4.5))
        self.assertEqual((found.window_days, found.stale_days), (90, 30))

    def test_the_latest_release_and_the_default_branchs_ci(self) -> None:
        facts = _asked(_github())[0]
        release = _one(facts, HostRelease)
        self.assertEqual((release.tag, release.date), ("v3.12.0", "2025-04-11"))
        ci = _one(facts, HostCi)
        self.assertEqual((ci.branch, ci.commit, ci.date, ci.state), ("develop", "3220638", "2026-11-23", "FAILURE"))
        # The suites of apps that never started (queued, no workflow run) are left out, and of the three runs of the
        # workflow Dependabot Updates on the commit only the latest counts: two suites, the longest 1 h 36 min.
        self.assertEqual(dict(ci.suites), {"SUCCESS": 2})
        self.assertEqual((ci.running, ci.seconds), (0, 5754))

    def test_security_alerts_are_counted_where_the_token_reads_them(self) -> None:
        facts = _asked(_github())[0]
        found = _one(facts, HostSecurity)
        self.assertEqual((found.dependabot, found.code_scanning, found.private_reporting), (None, 2, True))
        self.assertEqual(
            _unread(facts)["Dependabot alerts"],
            "You are not authorized to perform this operation. (HTTP 403; it needs a token that may read the "
            "repository's security alerts)",
        )

    def test_a_full_page_of_alerts_is_said_to_be_at_least_that_many(self) -> None:
        facts = _asked(_github(dependabot=[{"number": n} for n in range(100)]))[0]
        self.assertEqual(_one(facts, HostSecurity).dependabot, 100)
        self.assertTrue(_shown(facts)["security"].startswith("100 or more open Dependabot alerts; "))

    def test_a_graphql_query_refused_leaves_its_items_unread(self) -> None:
        facts = _asked(_github(graphql=Refused(502, "HTTP 502")))[0]
        self.assertEqual(
            {key: value for key, value in _unread(facts).items() if "alerts" not in key},
            {
                "activity": "GitHub did not answer (HTTP 502)",
                "releases": "GitHub did not answer (HTTP 502)",
                "default-branch CI": "GitHub did not answer (HTTP 502)",
            },
        )
        self.assertIsInstance(_one(facts, HostRepository), HostRepository)

    def test_graphql_errors_say_what_was_not_read(self) -> None:
        errors = {"data": {"repository": None, "stale": None}, "errors": [{"message": "Could not resolve"}]}
        self.assertEqual(_unread(_asked(_github(graphql=errors))[0])["activity"], "GitHub said: Could not resolve")

    def test_a_repository_without_releases_or_ci_says_so(self) -> None:
        answer = copy.deepcopy(ANSWERS["github_graphql"])
        answer["data"]["repository"]["latestRelease"] = None
        answer["data"]["repository"]["defaultBranchRef"]["target"]["statusCheckRollup"] = None
        answer["data"]["repository"]["defaultBranchRef"]["target"]["checkSuites"]["nodes"] = []
        facts = _asked(_github(graphql=answer))[0]
        self.assertIsNone(_one(facts, HostRelease).tag)
        ci = _one(facts, HostCi)
        self.assertEqual((ci.state, dict(ci.suites), ci.seconds), (None, {}, None))

    def test_another_host_says_its_details_are_not_read(self) -> None:
        answers = {
            "https://gitlab.com/api/v4/projects/g%2Fr": {"default_branch": "main"},
            "https://gitlab.com/api/v4/projects/g%2Fr/protected_branches/main": {},
            "https://gitlab.com/api/v4/projects/g%2Fr/approval_rules": [],
        }
        facts = _asked(answers, "git@gitlab.com:g/r.git")[0]
        self.assertEqual(_unread(facts), {"the host's details": "GitLab's are not read: only GitHub's, for now"})


def _shown(facts: list[Fact]) -> dict[str, str]:
    return {detail.subject: detail.text for detail in host(Facts(facts))}


# A repository with little activity: nothing closed or merged in the window.
QUIET = HostActivity(
    origin=ORIGIN,
    open_issues=1,
    open_pull_requests=0,
    stale_pull_requests=2,
    issues_closed=0,
    days_to_close=None,
    pull_requests_merged=0,
    days_to_merge=None,
    window_days=90,
    stale_days=30,
)


class ShownTests(unittest.TestCase):
    def test_each_item_is_shown_in_words(self) -> None:
        shown = _shown(_asked(_github())[0])
        self.assertEqual(
            shown["the repository"],
            "GitHub nlohmann/json: public, not archived, not a fork; topics bson, cbor, header-only, json, json-diff; "
            "homepage https://json.nlohmann.me; GitHub detects the MIT licence",
        )
        self.assertEqual(
            shown["activity"],
            "19 open issues and 29 open pull requests, none stale (not updated in 30 days); in the last 90 days, 6 "
            "issues closed in a median of 3.6 days and 5 pull requests merged in a median of 4.5 days",
        )
        self.assertEqual(
            shown["security"],
            "Dependabot alerts not read: You are not authorized to perform this operation. (HTTP 403; it needs a "
            "token that may read the repository's security alerts); 2 open code scanning alerts; private "
            "vulnerability reporting on",
        )
        self.assertEqual(shown["releases"], "latest release v3.12.0, of 2025-04-11")
        self.assertEqual(
            shown["default-branch CI"],
            "develop at 3220638 (2026-11-23): failure; 2 check suites (2 success), the longest 1 h 36 min",
        )

    def test_what_was_not_read_is_said_plainly(self) -> None:
        shown = _shown(_asked(_github(graphql=Refused(502, "HTTP 502")))[0])
        self.assertEqual(shown["activity"], "not read: GitHub did not answer (HTTP 502)")

    def test_a_repository_without_releases_or_ci_results_says_so(self) -> None:
        answer = copy.deepcopy(ANSWERS["github_graphql"])
        answer["data"]["repository"]["latestRelease"] = None
        target = answer["data"]["repository"]["defaultBranchRef"]["target"]
        target["statusCheckRollup"] = None
        target["checkSuites"]["nodes"] = [
            {**target["checkSuites"]["nodes"][0], "status": "IN_PROGRESS", "conclusion": None}
        ]
        shown = _shown(_asked(_github(graphql=answer))[0])
        self.assertEqual(shown["releases"], "no releases on GitHub")
        self.assertEqual(
            shown["default-branch CI"], "develop at 3220638 (2026-11-23): no result yet; 1 check suite (1 running)"
        )

    def test_quiet_repositories_short_runs_and_unread_reporting_are_said(self) -> None:
        security = HostSecurity(origin=ORIGIN, dependabot=0, code_scanning=1)
        unread = HostUnread(origin=ORIGIN, item="private vulnerability reporting", reason="HTTP 404")
        runs = [
            HostCi(origin=ORIGIN, branch="main", commit="abc1234", date="2026-11-01", state="SUCCESS", seconds=s)
            for s in (20, 300)
        ]
        shown = [detail.text for detail in host(Facts([QUIET, security, unread, *runs]))]
        self.assertEqual(
            shown,
            [
                "1 open issue and 0 open pull requests, 2 stale (not updated in 30 days); in the last 90 days, no "
                "issues closed and no pull requests merged",
                "0 open Dependabot alerts; 1 open code scanning alert; private vulnerability reporting not read: "
                "HTTP 404",
                "main at abc1234 (2026-11-01): success; no check suites, the longest under a minute",
                "main at abc1234 (2026-11-01): success; no check suites, the longest 5 min",
            ],
        )

    def test_a_repository_without_a_default_branch_and_a_refused_reporting_say_so(self) -> None:
        answer = copy.deepcopy(ANSWERS["github_graphql"])
        answer["data"]["repository"]["defaultBranchRef"] = None
        answers = _github(graphql=answer)
        answers[f"{REPOSITORY}/private-vulnerability-reporting"] = Refused(404, "HTTP 404", "Not Found")
        unread = _unread(_asked(answers)[0])
        self.assertEqual(unread["default-branch CI"], "the repository has no default branch")
        self.assertEqual(unread["private vulnerability reporting"], "Not Found (HTTP 404)")

    def test_offline_or_without_a_token_nothing_is_shown(self) -> None:
        # The Host line says why the host was not asked; the section does not repeat it.
        access = HostAccess(origin=ORIGIN, reason="the source-control host is not asked offline (--offline)")
        self.assertEqual(list(host(Facts([access]))), [])


if __name__ == "__main__":
    unittest.main()
