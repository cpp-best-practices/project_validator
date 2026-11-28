"""What the project's source-control host says of its repository (upstream #385): whether the default branch is
protected, with which required status checks and how many required reviews, and which of the host's security features
are on. It is shown with what was detected (`views.common.host_summary`), never judged: it depends on who asks, with
which token, so no check scores it. None of it is in the checkout: it is asked of the host's API, for the repository the
`origin` remote names, with a token the user has (an environment variable, or the `gh` CLI's login for GitHub).

Without an origin remote, a host the validator does not read, a token, or the token's access, the settings are not read,
and `HostAccess` says why; the views say so. `--offline` (or `PROJECT_VALIDATOR_OFFLINE`) never asks; the test suite and
the corpus run offline, so that what they record does not depend on the network.

GitHub's branch rules (rulesets) are readable with any token that reads the repository; its classic branch
protection and its security settings need admin access, and are read where the token has it. GitLab's protected
branches and approval rules, Gitea's and Forgejo's branch protections (Codeberg), and Bitbucket Cloud's branch
restrictions are read where the token allows.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol

from project_validator.facts import NOTHING, Fact, Origin

OFFLINE_VARIABLE = "PROJECT_VALIDATOR_OFFLINE"
_TIMEOUT = 10

_SSH = re.compile(r"^(?:ssh://)?git@(?P<host>[^:/]+)[:/](?P<path>.+?)(?:\.git)?/?$")
_HTTPS = re.compile(r"^https?://(?:[^@/]+@)?(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?/?$")


@dataclass(frozen=True, slots=True)
class Remote:
    """A repository on a host: `github.com` and `owner/name` (a group path on GitLab)."""

    host: str
    path: str


def remote_of(url: str) -> Remote | None:
    """The host and repository path of a git remote's URL (`git@github.com:o/r.git` is github.com, o/r)."""
    found = _SSH.match(url) or _HTTPS.match(url)
    return Remote(found["host"].lower(), found["path"]) if found else None


@dataclass(frozen=True, slots=True, kw_only=True)
class HostSettings(Fact):
    """What the host says of the repository: its default `branch`; whether it is `protected` (None: not read); the
    status checks it requires and the reviews it requires before a merge (None: not read); and each security feature
    the host has, on or off (one missing was not read). `unread` says what could not be read, and why."""

    host: str
    repository: str
    branch: str
    protected: bool | None = None
    required_checks: tuple[str, ...] | None = None
    required_reviews: int | None = None
    security: Mapping[str, bool] = NOTHING
    unread: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class HostAccess(Fact):
    """Why the host's settings were not read: no origin remote, a host the validator does not read, no token, or a
    host that refused."""

    reason: str


class Refused(Exception):
    """The host answered with an error (`status`), or not at all (0); `detail` is what its answer said of the error
    (GitHub's `message`: "Dependabot alerts are disabled for this repository."), if anything."""

    def __init__(self, status: int, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


type Get = Callable[[str], object]


class Ask(Protocol):
    """A GET of a URL, or a POST of a JSON `body` to it (a GraphQL query), answered with the JSON the host sends."""

    def __call__(self, url: str, body: Mapping[str, object] | None = None, /) -> object: ...


def _said(error: urllib.error.HTTPError) -> str:
    """The `message` an API's error answer holds, if it is JSON that has one."""
    try:
        answer = json.loads(error.read() or b"null")
    except (ValueError, OSError):
        return ""
    return str(answer.get("message") or "") if isinstance(answer, dict) else ""


def fetch(url: str, headers: Mapping[str, str], body: Mapping[str, object] | None = None) -> object:
    """The JSON a GET of `url` answers, or a POST of `body` (None for an empty answer); `Refused` for an error status
    or no answer."""
    data = None if body is None else json.dumps(body).encode()
    sent = dict(headers) | ({} if data is None else {"Content-Type": "application/json"})
    request = urllib.request.Request(url, data=data, headers=sent)  # noqa: S310 - an https API
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as answer:  # noqa: S310 - an https API
            read = answer.read()
    except urllib.error.HTTPError as error:
        raise Refused(error.code, f"HTTP {error.code}", _said(error)) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise Refused(0, str(getattr(error, "reason", error))) from error
    return json.loads(read) if read.strip() else None


class _Asked:
    """`fetch` with the host's headers, each URL (and body) asked once in a run: the settings and the details share
    the repository's answer. A refusal is remembered too, and raised again."""

    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = headers
        self._answers: dict[str, object] = {}

    def _answer(self, url: str, body: Mapping[str, object] | None) -> object:
        try:
            return fetch(url, self._headers) if body is None else fetch(url, self._headers, body)
        except Refused as error:
            return error

    def __call__(self, url: str, body: Mapping[str, object] | None = None, /) -> object:
        key = url if body is None else f"{url} {json.dumps(body, sort_keys=True)}"
        if key not in self._answers:
            self._answers[key] = self._answer(url, body)
        if isinstance(answer := self._answers[key], Refused):
            raise answer
        return answer


def _environment_token(*names: str) -> str | None:
    return next((value for name in names if (value := os.environ.get(name))), None)


def _gh_token() -> str | None:
    """The token the `gh` CLI is logged in with, if it is installed and logged in."""
    if shutil.which("gh") is None:
        return None
    try:
        found = subprocess.run(
            ["gh", "auth", "token"],  # noqa: S607 - gh from PATH, as the user runs it
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return found.stdout.strip() or None if found.returncode == 0 else None


# --- GitHub ----------------------------------------------------------------------------------------------------------

# The security settings GitHub reports to an admin (`security_and_analysis`), by what each is called here.
_GITHUB_SECURITY = {
    "secret scanning": "secret_scanning",
    "secret scanning push protection": "secret_scanning_push_protection",
    "Dependabot security updates": "dependabot_security_updates",
}


def _github_rules(rules: object) -> tuple[bool, tuple[str, ...], int]:
    """Whether a branch's rules protect it, the status checks they require, and the reviews they require."""
    listed = [rule for rule in rules if isinstance(rule, dict)] if isinstance(rules, list) else []
    checks: list[str] = []
    reviews = 0
    for rule in listed:
        parameters = rule.get("parameters") or {}
        # Only a required_status_checks rule names them.
        checks += [str(check.get("context")) for check in parameters.get("required_status_checks", [])]
        if rule.get("type") == "pull_request":
            reviews = max(reviews, int(parameters.get("required_approving_review_count") or 0))
    return bool(listed), tuple(checks), reviews


def _github_protection(protection: object) -> tuple[tuple[str, ...], int]:
    """The status checks and reviews classic branch protection requires."""
    found = protection if isinstance(protection, dict) else {}
    checks = found.get("required_status_checks") or {}
    contexts = [str(name) for name in checks.get("contexts", [])] if isinstance(checks, dict) else []
    reviews = found.get("required_pull_request_reviews") or {}
    count = int(reviews.get("required_approving_review_count") or 0) if isinstance(reviews, dict) else 0
    return tuple(contexts), count


def _github_classic(get: Get, url: str, unread: list[str]) -> tuple[tuple[str, ...], int] | None:
    """What classic branch protection requires; None when the branch has none, or the token cannot read it (said in
    `unread`)."""
    try:
        return _github_protection(get(url))
    except Refused as error:
        if error.status != 404:  # 404: the branch has no classic protection
            unread.append(f"classic branch protection ({error}: it needs admin access)")
        return None


def _github_security(repository: Mapping[str, object], unread: list[str]) -> dict[str, bool]:
    """Each security setting GitHub reports, on or off; none when the token cannot read them (said in `unread`)."""
    analysis = repository.get("security_and_analysis")
    found = analysis if isinstance(analysis, dict) else {}
    security = {
        name: (found.get(key) or {}).get("status") == "enabled"
        for name, key in _GITHUB_SECURITY.items()
        if key in found
    }
    if not security:
        unread.append("the security settings (they need admin access)")
    return security


def github_api(remote: Remote) -> str:
    """The root of GitHub's REST API for `remote`: api.github.com, or a GitHub Enterprise server's /api/v3."""
    return "https://api.github.com" if remote.host == "github.com" else f"https://{remote.host}/api/v3"


def _github(remote: Remote, get: Get, origin: Origin) -> HostSettings:
    base = f"{github_api(remote)}/repos/{remote.path}"
    answer = get(base)
    repository = answer if isinstance(answer, dict) else {}
    branch = str(repository.get("default_branch") or "main")
    quoted = urllib.parse.quote(branch)
    ruled, rule_checks, rule_reviews = _github_rules(get(f"{base}/rules/branches/{quoted}"))
    protected: bool | None = ruled
    checks: tuple[str, ...] | None = rule_checks
    reviews: int | None = rule_reviews
    unread: list[str] = []
    if (classic := _github_classic(get, f"{base}/branches/{quoted}/protection", unread)) is not None:
        protected, checks, reviews = True, (*rule_checks, *classic[0]), max(rule_reviews, classic[1])
    elif unread and not ruled:  # no rules, and classic protection the token cannot read: not known
        protected, checks, reviews = None, None, None
    return HostSettings(
        origin=origin,
        host="GitHub",
        repository=remote.path,
        branch=branch,
        protected=protected,
        required_checks=None if checks is None else tuple(dict.fromkeys(checks)),
        required_reviews=reviews,
        security=_github_security(repository, unread),
        unread=tuple(unread),
    )


# --- GitLab ----------------------------------------------------------------------------------------------------------


def _gitlab(remote: Remote, get: Get, origin: Origin) -> HostSettings:
    base = f"https://{remote.host}/api/v4/projects/{urllib.parse.quote(remote.path, safe='')}"
    project = get(base)
    found = project if isinstance(project, dict) else {}
    branch = str(found.get("default_branch") or "main")
    try:
        get(f"{base}/protected_branches/{urllib.parse.quote(branch, safe='')}")
        protected = True
    except Refused as error:
        if error.status != 404:
            raise
        protected = False
    rules = get(f"{base}/approval_rules")
    approvals = (
        [int(rule.get("approvals_required") or 0) for rule in rules if isinstance(rule, dict)]
        if isinstance(rules, list)
        else []
    )
    pipeline = bool(found.get("only_allow_merge_if_pipeline_succeeds"))
    return HostSettings(
        origin=origin,
        host="GitLab",
        repository=remote.path,
        branch=branch,
        protected=protected,
        required_checks=("the pipeline",) if pipeline else (),
        required_reviews=max(approvals, default=0),
        unread=("the security settings (GitLab's are not read)",),
    )


# --- Gitea and Forgejo (Codeberg) ------------------------------------------------------------------------------------


def _gitea(remote: Remote, get: Get, origin: Origin) -> HostSettings:
    base = f"https://{remote.host}/api/v1/repos/{remote.path}"
    repository = get(base)
    found = repository if isinstance(repository, dict) else {}
    branch = str(found.get("default_branch") or "main")
    protections = get(f"{base}/branch_protections")
    rules = [
        rule
        for rule in (protections if isinstance(protections, list) else [])
        if isinstance(rule, dict) and branch in (rule.get("branch_name"), rule.get("rule_name"))
    ]
    checks = [
        str(name)
        for rule in rules
        if rule.get("enable_status_check")
        for name in rule.get("status_check_contexts") or ["*"]
    ]
    return HostSettings(
        origin=origin,
        host="Gitea",
        repository=remote.path,
        branch=branch,
        protected=bool(rules),
        required_checks=tuple(checks),
        required_reviews=max((int(rule.get("required_approvals") or 0) for rule in rules), default=0),
        unread=("the security settings (Gitea's are not read)",),
    )


# --- Bitbucket Cloud -------------------------------------------------------------------------------------------------


def _bitbucket(remote: Remote, get: Get, origin: Origin) -> HostSettings:
    base = f"https://api.bitbucket.org/2.0/repositories/{remote.path}"
    repository = get(base)
    found = repository if isinstance(repository, dict) else {}
    branch = str((found.get("mainbranch") or {}).get("name") or "main")
    answer = get(f"{base}/branch-restrictions")
    values = answer.get("values") if isinstance(answer, dict) else None
    rules = [rule for rule in (values or []) if isinstance(rule, dict) and rule.get("pattern") in (branch, "*")]
    kinds = {str(rule.get("kind")): int(rule.get("value") or 0) for rule in rules}
    builds = kinds.get("require_passing_builds_to_merge", 0)
    return HostSettings(
        origin=origin,
        host="Bitbucket",
        repository=remote.path,
        branch=branch,
        protected=bool(rules),
        required_checks=("passing builds",) if builds else (),
        required_reviews=kinds.get("require_approvals_to_merge", 0),
        unread=("the security settings (Bitbucket's are not read)",),
    )


# --- Which host, with which token ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Host:
    name: str
    matches: Callable[[str], bool]
    token: Callable[[], str | None]
    headers: Callable[[str], dict[str, str]]
    read: Callable[[Remote, Get, Origin], HostSettings]
    how: str  # how to give the validator a token


HOSTS = (
    _Host(
        "GitHub",
        lambda host: host == "github.com",
        lambda: _environment_token("GH_TOKEN", "GITHUB_TOKEN") or _gh_token(),
        lambda token: {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        _github,
        "set GH_TOKEN or GITHUB_TOKEN, or log in with `gh auth login`",
    ),
    _Host(
        "GitLab",
        lambda host: host.startswith("gitlab."),  # gitlab.com, and self-hosted gitlab.<domain>
        lambda: _environment_token("GITLAB_TOKEN"),
        lambda token: {"PRIVATE-TOKEN": token},
        _gitlab,
        "set GITLAB_TOKEN",
    ),
    _Host(
        "Gitea",
        lambda host: host == "codeberg.org" or host.startswith(("gitea.", "forgejo.")),
        lambda: _environment_token("GITEA_TOKEN", "FORGEJO_TOKEN", "CODEBERG_TOKEN"),
        lambda token: {"Authorization": f"token {token}"},
        _gitea,
        "set GITEA_TOKEN (or FORGEJO_TOKEN, CODEBERG_TOKEN)",
    ),
    _Host(
        "Bitbucket",
        lambda host: host == "bitbucket.org",
        lambda: _environment_token("BITBUCKET_TOKEN"),
        lambda token: {"Authorization": f"Bearer {token}"},
        _bitbucket,
        "set BITBUCKET_TOKEN",
    ),
)
_ORIGIN = Origin(path=".git/config")


def offline(requested: bool) -> bool:
    """Whether the host is never asked: `--offline`, or `PROJECT_VALIDATOR_OFFLINE` set to anything but empty."""
    return requested or bool(os.environ.get(OFFLINE_VARIABLE))


type Details = Callable[[Remote, Ask, Origin], Iterator[Fact]]


def host_facts(
    url: str | None, *, requested_offline: bool = False, details: Mapping[str, Details] = NOTHING
) -> Iterator[Fact]:
    """What the host of the `origin` remote at `url` says of the repository, or why it was not asked: its settings,
    then what the reader of `details` for the host (by its name: `host_details.DETAILS`) reads, asking each URL once."""
    if offline(requested_offline):
        yield HostAccess(origin=_ORIGIN, reason="the source-control host is not asked offline (--offline)")
        return
    remote = remote_of(url or "")
    if remote is None:
        yield HostAccess(origin=_ORIGIN, reason="the project has no origin remote on a host to ask")
        return
    host = next((found for found in HOSTS if found.matches(remote.host)), None)
    if host is None:
        names = ", ".join(found.name for found in HOSTS)
        yield HostAccess(origin=_ORIGIN, reason=f"{remote.host} is not a host the validator reads ({names})")
        return
    token = host.token()
    if token is None:
        yield HostAccess(origin=_ORIGIN, reason=f"no token to ask {host.name}: {host.how}")
        return
    ask = _Asked(host.headers(token))
    try:
        yield host.read(remote, ask, _ORIGIN)
    except Refused as error:
        yield HostAccess(origin=_ORIGIN, reason=f"{host.name} did not answer for {remote.path}: {error}")
        return
    if (reader := details.get(host.name)) is not None:
        yield from reader(remote, ask, _ORIGIN)


__all__ = [
    "HOSTS",
    "Ask",
    "Details",
    "HostAccess",
    "HostSettings",
    "Refused",
    "Remote",
    "fetch",
    "github_api",
    "host_facts",
    "offline",
    "remote_of",
]
