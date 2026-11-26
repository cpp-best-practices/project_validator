"""The source-control host's settings (upstream #385): read from a fake host, never the network."""

from __future__ import annotations

import os
import unittest
from collections.abc import Mapping, Sequence
from unittest import mock

from project_validator import hosting
from project_validator.hosting import HostAccess, HostSettings, Refused, Remote, host_facts, remote_of

GITHUB = "https://api.github.com/repos/o/r"
RULES = [
    {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "build"}]}},
    {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
    {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},  # a looser ruleset beside it
]
SECURITY = {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "disabled"},
    "dependabot_security_updates": {"status": "enabled"},
}


def _host(answers: Mapping[str, object]):  # type: ignore[no-untyped-def]
    """A fake `fetch`: each URL's answer; a `Refused` answer is raised; any other URL is a 404."""

    def fetch(url: str, headers: Mapping[str, str]) -> object:
        del headers
        answer = answers.get(url, Refused(404, "HTTP 404"))
        if isinstance(answer, Refused):
            raise answer
        return answer

    return fetch


def _one[T](facts: Sequence[object], kind: type[T]) -> T:
    """The one fact of `kind` among `facts`, which must be all there is."""
    [found] = facts
    if not isinstance(found, kind):
        raise AssertionError(f"{found!r} is not a {kind.__name__}")
    return found


def _asked(url: str, answers: Mapping[str, object], token: Mapping[str, str] | None = None) -> list[object]:
    """The facts `host_facts` gives for the remote at `url`, online, with `token` (GH_TOKEN by default)."""
    environment = {key: value for key, value in os.environ.items() if key != hosting.OFFLINE_VARIABLE}
    with (
        mock.patch.dict(os.environ, {**environment, **(token if token is not None else {"GH_TOKEN": "t"})}, clear=True),
        mock.patch.object(hosting, "fetch", _host(answers)),
        mock.patch.object(hosting, "_gh_token", return_value=None),
    ):
        return list(host_facts(url))


class RemoteTests(unittest.TestCase):
    def test_a_remote_names_its_host_and_repository(self) -> None:
        for url in ("git@github.com:o/r.git", "https://github.com/o/r", "ssh://git@GitHub.com/o/r.git"):
            with self.subTest(url=url):
                self.assertEqual(remote_of(url), Remote("github.com", "o/r"))
        self.assertEqual(remote_of("https://gitlab.com/group/sub/r.git"), Remote("gitlab.com", "group/sub/r"))
        self.assertIsNone(remote_of("/home/me/r"))


class AccessTests(unittest.TestCase):
    def _reason(self, facts: Sequence[object]) -> str:
        return _one(facts, HostAccess).reason

    def test_offline_the_host_is_never_asked(self) -> None:
        with mock.patch.object(hosting, "fetch", side_effect=AssertionError("asked")):
            environment = {key: value for key, value in os.environ.items() if key != hosting.OFFLINE_VARIABLE}
            with mock.patch.dict(os.environ, environment, clear=True):
                asked = list(host_facts("git@github.com:o/r.git", requested_offline=True))
            self.assertIn("offline", self._reason(asked))
            # The test suite runs offline (tests/__init__.py).
            self.assertIn("offline", self._reason(list(host_facts("git@github.com:o/r.git"))))

    def test_without_a_remote_a_known_host_or_a_token_it_says_why(self) -> None:
        self.assertIn("no origin remote", self._reason(_asked("", {})))
        self.assertIn("no origin remote", self._reason(_asked("/home/me/r", {})))
        self.assertIn("example.org is not a host the validator reads", self._reason(_asked("git@example.org:o/r", {})))
        self.assertIn("no token to ask GitHub: set GH_TOKEN", self._reason(_asked("git@github.com:o/r", {}, token={})))

    def test_the_gh_login_is_a_token(self) -> None:
        environment = {key: value for key, value in os.environ.items() if key not in ("GH_TOKEN", "GITHUB_TOKEN")}
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch.object(hosting, "_gh_token", return_value="g"),
        ):
            self.assertEqual(hosting.HOSTS[0].token(), "g")

    def test_a_host_that_refuses_says_so(self) -> None:
        refused = _asked("git@github.com:o/r", {GITHUB: Refused(403, "HTTP 403")})
        self.assertEqual(self._reason(refused), "GitHub did not answer for o/r: HTTP 403")


class GitHubTests(unittest.TestCase):
    def _settings(self, answers: Mapping[str, object]) -> HostSettings:
        return _one(_asked("git@github.com:o/r.git", answers), HostSettings)

    def test_the_rules_say_what_the_default_branch_requires(self) -> None:
        settings = self._settings({GITHUB: {"default_branch": "trunk"}, f"{GITHUB}/rules/branches/trunk": RULES})
        self.assertEqual(
            (settings.branch, settings.protected, settings.required_checks, settings.required_reviews),
            ("trunk", True, ("build",), 1),
        )
        self.assertEqual(settings.unread, ("the security settings (they need admin access)",))

    def test_classic_protection_and_the_security_settings_where_the_token_reads_them(self) -> None:
        classic = {
            "required_status_checks": {"contexts": ["test"]},
            "required_pull_request_reviews": {"required_approving_review_count": 2},
        }
        settings = self._settings(
            {
                GITHUB: {"default_branch": "main", "security_and_analysis": SECURITY},
                f"{GITHUB}/rules/branches/main": [],
                f"{GITHUB}/branches/main/protection": classic,
            }
        )
        self.assertEqual(
            (settings.protected, settings.required_checks, settings.required_reviews), (True, ("test",), 2)
        )
        self.assertEqual(
            dict(settings.security),
            {"secret scanning": True, "secret scanning push protection": False, "Dependabot security updates": True},
        )
        self.assertEqual(settings.unread, ())

    def test_an_unprotected_branch_and_protection_the_token_cannot_read(self) -> None:
        unprotected = self._settings({GITHUB: {"default_branch": "main"}, f"{GITHUB}/rules/branches/main": []})
        self.assertFalse(unprotected.protected)
        denied = self._settings(
            {
                GITHUB: {"default_branch": "main"},
                f"{GITHUB}/rules/branches/main": [],
                f"{GITHUB}/branches/main/protection": Refused(403, "HTTP 403"),
            }
        )
        self.assertIn("classic branch protection (HTTP 403: it needs admin access)", denied.unread)
        # No rules, and classic protection unread: whether the branch is protected is not known.
        self.assertEqual((denied.protected, denied.required_checks, denied.required_reviews), (None, None, None))
        ruled = self._settings(
            {
                GITHUB: {"default_branch": "main"},
                f"{GITHUB}/rules/branches/main": RULES,
                f"{GITHUB}/branches/main/protection": Refused(403, "HTTP 403"),
            }
        )
        self.assertEqual((ruled.protected, ruled.required_checks, ruled.required_reviews), (True, ("build",), 1))


class OtherHostTests(unittest.TestCase):
    def test_gitlab(self) -> None:
        base = "https://gitlab.com/api/v4/projects/g%2Fr"
        answers = {
            base: {"default_branch": "main", "only_allow_merge_if_pipeline_succeeds": True},
            f"{base}/protected_branches/main": {"name": "main"},
            f"{base}/approval_rules": [{"approvals_required": 2}, {"approvals_required": 1}],
        }
        settings = _one(_asked("git@gitlab.com:g/r.git", answers, token={"GITLAB_TOKEN": "t"}), HostSettings)
        self.assertEqual(
            (settings.host, settings.protected, settings.required_checks, settings.required_reviews),
            ("GitLab", True, ("the pipeline",), 2),
        )
        unprotected = _one(
            _asked("git@gitlab.com:g/r.git", {base: {}, f"{base}/approval_rules": []}, {"GITLAB_TOKEN": "t"}),
            HostSettings,
        )
        self.assertEqual((unprotected.protected, unprotected.required_checks), (False, ()))
        denied = {base: {}, f"{base}/protected_branches/main": Refused(401, "HTTP 401"), f"{base}/approval_rules": []}
        _one(_asked("git@gitlab.com:g/r.git", denied, {"GITLAB_TOKEN": "t"}), HostAccess)

    def test_gitea_and_forgejo(self) -> None:
        base = "https://codeberg.org/api/v1/repos/o/r"
        rule = {
            "branch_name": "main",
            "enable_status_check": True,
            "status_check_contexts": ["ci"],
            "required_approvals": 1,
        }
        other = {"branch_name": "release", "required_approvals": 3}
        answers = {base: {"default_branch": "main"}, f"{base}/branch_protections": [rule, other]}
        settings = _one(_asked("https://codeberg.org/o/r", answers, token={"FORGEJO_TOKEN": "t"}), HostSettings)
        self.assertEqual(
            (settings.host, settings.protected, settings.required_checks, settings.required_reviews),
            ("Gitea", True, ("ci",), 1),
        )
        # Status checks named but not enabled are not required.
        off = {**answers, f"{base}/branch_protections": [{**rule, "enable_status_check": False}]}
        self.assertEqual(
            _one(_asked("https://codeberg.org/o/r", off, {"FORGEJO_TOKEN": "t"}), HostSettings).required_checks, ()
        )

    def test_bitbucket(self) -> None:
        base = "https://api.bitbucket.org/2.0/repositories/w/r"
        restrictions = [
            {"kind": "require_approvals_to_merge", "pattern": "main", "value": 2},
            {"kind": "require_passing_builds_to_merge", "pattern": "main", "value": 1},
            {"kind": "push", "pattern": "release"},
        ]
        answers = {base: {"mainbranch": {"name": "main"}}, f"{base}/branch-restrictions": {"values": restrictions}}
        settings = _one(_asked("git@bitbucket.org:w/r.git", answers, token={"BITBUCKET_TOKEN": "t"}), HostSettings)
        self.assertEqual(
            (settings.host, settings.protected, settings.required_checks, settings.required_reviews),
            ("Bitbucket", True, ("passing builds",), 2),
        )
        # A restriction of another branch does not protect the main one.
        elsewhere = {**answers, f"{base}/branch-restrictions": {"values": restrictions[2:]}}
        unprotected = _one(_asked("git@bitbucket.org:w/r.git", elsewhere, {"BITBUCKET_TOKEN": "t"}), HostSettings)
        self.assertFalse(unprotected.protected)
