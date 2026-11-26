"""`--fetch-remote` (upstream #248): a reusable workflow or a composite action of another repository is read at the
ref it is pinned to, fetched from GitHub; without the option, or offline, it is not read, as before."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from project_validator import remote
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Options, Result, Status
from project_validator.facts import Command, Unknown
from tests.support import GITHUB_WORKFLOW, make_context, temp_project

SHA = "0123456789abcdef0123456789abcdef01234567"
# graphql-eslint lints in a reusable workflow of another repository (the-guild-org/shared-config).
LINT_WORKFLOW = {
    "on": {"workflow_call": {}},
    "jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": [{"run": "npx eslint ."}]}},
}
CALLER = {"jobs": {"lint": {"uses": f"the-guild-org/shared-config/.github/workflows/lint.yml@{SHA}"}}}
COMPOSITE = {"name": "lint", "runs": {"using": "composite", "steps": [{"run": "npx eslint .", "shell": "bash"}]}}
PROJECT = {"package.json": json.dumps({"name": "x"}), "index.js": "", ".eslintrc.json": "{}"}
# As GitHub serves them: owner/repo/ref/path.
FILES = {
    f"the-guild-org/shared-config/{SHA}/.github/workflows/lint.yml": json.dumps(LINT_WORKFLOW),
    f"some-org/composite-actions/{SHA}/lint/action.yml": json.dumps(COMPOSITE),
    "the-guild-org/shared-config/v1/.github/workflows/lint.yml": json.dumps(LINT_WORKFLOW),
}


@contextmanager
def _online(files: Mapping[str, str] = FILES) -> Iterator[list[str]]:
    """The network as `files` (owner/repo/ref/path -> text), with an empty cache; yields the paths fetched."""
    fetched: list[str] = []

    def get(url: str) -> str | None:
        path = url.removeprefix("https://raw.githubusercontent.com/")
        fetched.append(path)
        return files.get(path)

    with (
        tempfile.TemporaryDirectory() as cache,
        mock.patch.dict(os.environ, {"PROJECT_VALIDATOR_OFFLINE": "", "XDG_CACHE_HOME": cache}),
        mock.patch.object(remote, "_get", side_effect=get),
    ):
        yield fetched


def _result(files: Mapping[str, str], *, fetch_remote: bool = False, offline: bool = False) -> Result:
    with temp_project({**PROJECT, **files}) as root:
        return static_analysis.run(make_context(root, Options(fetch_remote=fetch_remote, offline=offline)))


def _commands(files: Mapping[str, str], *, fetch_remote: bool = False) -> list[tuple[str, ...]]:
    with temp_project({**PROJECT, **files}) as root:
        context = make_context(root, Options(fetch_remote=fetch_remote))
        return [command.argv for command in context.facts.of(Command)]


class FetchRemoteTests(unittest.TestCase):
    def test_a_reusable_workflow_of_another_repository_is_read_when_asked(self) -> None:
        caller = {GITHUB_WORKFLOW: json.dumps(CALLER)}
        with _online():
            self.assertEqual(_result(caller, fetch_remote=True).status, Status.PASS)
            unread = _result(caller)
        self.assertEqual(unread.status, Status.ERROR, unread)
        self.assertIn("--fetch-remote", " ".join(unread.details))

    def test_a_composite_action_of_another_repository_runs_its_steps(self) -> None:
        step = {
            "jobs": {
                "lint": {"runs-on": "ubuntu-latest", "steps": [{"uses": f"some-org/composite-actions/lint@{SHA}"}]}
            }
        }
        files = {GITHUB_WORKFLOW: json.dumps(step)}
        with _online():
            self.assertIn(("npx", "eslint", "."), _commands(files, fetch_remote=True))
            self.assertNotIn(("npx", "eslint", "."), _commands(files))

    def test_an_action_the_validator_knows_is_not_fetched(self) -> None:
        step = {"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": [{"uses": "rhysd/actionlint@v1"}]}}}
        with _online() as fetched:
            _commands({GITHUB_WORKFLOW: json.dumps(step)}, fetch_remote=True)
        self.assertEqual(fetched, [])

    def test_offline_nothing_is_fetched(self) -> None:
        caller = {GITHUB_WORKFLOW: json.dumps(CALLER)}
        with _online() as fetched:
            result = _result(caller, fetch_remote=True, offline=True)
        self.assertEqual((fetched, result.status), ([], Status.ERROR))

    def test_a_file_pinned_to_a_commit_is_fetched_once(self) -> None:
        key = remote.reference("the-guild-org/shared-config", ".github/workflows/lint.yml", SHA)
        with _online() as fetched:
            self.assertEqual(
                remote.fetched(key), FILES[f"the-guild-org/shared-config/{SHA}/.github/workflows/lint.yml"]
            )
            self.assertIsNotNone(remote.fetched(key))
            self.assertEqual(len(fetched), 1)
            cached = Path(os.environ["XDG_CACHE_HOME"], "project_validator", "remote")
            self.assertTrue(any(cached.rglob("lint.yml")))
            # A tag can move: it is fetched each time.
            tag = remote.reference("the-guild-org/shared-config", ".github/workflows/lint.yml", "v1")
            remote.fetched(tag)
            self.assertFalse(any(cached.joinpath("v1").rglob("*")))  # never cached
            stale = cached.joinpath("v1", "the-guild-org", "shared-config", ".github", "workflows", "lint.yml")
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")
            self.assertNotEqual(remote.fetched(tag), "stale")  # nor read from a cache
            self.assertEqual(len(fetched), 3)

    def test_a_remote_action_without_its_definition_is_unknown(self) -> None:
        uses = f"some-org/composite-actions/missing@{SHA}"
        step = {"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": [{"uses": uses}]}}}
        with _online(), temp_project({**PROJECT, GITHUB_WORKFLOW: json.dumps(step)}) as root:
            facts = make_context(root, Options(fetch_remote=True)).facts
        subjects = [unknown.subject for unknown in facts.of(Unknown)]
        self.assertIn(f"the action {uses}", subjects)

    def test_a_remote_workflow_that_does_not_parse_is_not_read(self) -> None:
        broken = {f"the-guild-org/shared-config/{SHA}/.github/workflows/lint.yml": "jobs: [unclosed\n"}
        with _online(broken):
            result = _result({GITHUB_WORKFLOW: json.dumps(CALLER)}, fetch_remote=True)
        self.assertEqual(result.status, Status.ERROR, result)

    def test_a_docker_image_is_no_remote_action(self) -> None:
        step = {"jobs": {"lint": {"runs-on": "ubuntu-latest", "steps": [{"uses": "docker://alpine:3.20"}]}}}
        with _online() as fetched:
            _commands({GITHUB_WORKFLOW: json.dumps(step)}, fetch_remote=True)
        self.assertEqual(fetched, [])

    def test_a_malformed_name_is_never_fetched(self) -> None:
        with _online() as fetched:
            for name in ("remote:main/only-owner", "remote:main/o/r/../../etc/passwd", "remote:ma in/o/r/x.yml"):
                with self.subTest(name=name):
                    self.assertIsNone(remote.fetched(name))
        self.assertEqual(fetched, [])


class GetTests(unittest.TestCase):
    def test_get_reads_the_text_or_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            found = Path(directory, "a.yml")
            found.write_bytes(b"on: push\n")  # as served: Windows would write text with \r\n
            self.assertEqual(remote._get(found.as_uri()), "on: push\n")
            self.assertIsNone(remote._get(Path(directory, "missing.yml").as_uri()))


if __name__ == "__main__":
    unittest.main()
