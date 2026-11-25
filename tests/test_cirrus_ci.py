"""Cirrus CI: `.cirrus.yml` read as its tasks (`task:`, `<name>_task:`, each leg of a `matrix:` a task of its own),
each on the instance it names, with the commands of its scripts."""

from __future__ import annotations

import unittest

from project_validator.facts import CiJob, Command, Facts, Unknown
from tests.support import argvs, make_context, temp_project

# clj-kondo's: one task on a macOS instance written at the top.
CLJ_KONDO = """\
macos_instance:
  image: ghcr.io/cirruslabs/macos-monterey-base:latest

task:
  env:
    LEIN_ROOT: "true"
    CLJ_KONDO_ARCH: aarch64
  script: |
    script/compile
    script/test
    bb release-artifact "clj-kondo-$CLJ_KONDO_ARCH.zip" || true
  binaries_artifacts:
    path: "clj-kondo-*.zip"
"""

# Tasks named by their keys, each on its own instance or the top's.
NAMED = """\
container:
  image: python:3.12
env:
  PY: "3.12"
lint_task:
  lint_script: ruff check .
  types_script:
    - mypy .
    - pytest | tee log
windows_task:
  name: Windows tests
  windows_container:
    image: cirrusci/windowsservercore:2019
  test_script: pytest -k 'not slow'
freebsd_task:
  freebsd_instance:
    image_family: freebsd-14-0
  test_script: python$PY -m pytest
mac_docker_builder:
  build_script: docker build .
win_docker_builder:
  platform: windows
  build_script: docker build .
"""


def _facts(text: str) -> Facts:
    with temp_project({".cirrus.yml": text, "deps.edn": "{}\n"}) as root:
        return make_context(root).facts


def _jobs(facts: Facts) -> list[tuple[str, str, str, str | None]]:
    return [(job.id, job.name, job.os, job.image) for job in facts.of(CiJob)]


class CirrusCiTests(unittest.TestCase):
    def test_a_task_runs_its_script_on_the_instance_written_at_the_top(self) -> None:
        facts = _facts(CLJ_KONDO)
        self.assertEqual(_jobs(facts), [(".cirrus.yml:main", "main", "macos", None)])
        self.assertEqual(
            argvs(facts),
            [
                ("script/compile",),
                ("script/test",),
                ("bb", "release-artifact", "clj-kondo-$CLJ_KONDO_ARCH.zip"),
                ("true",),
            ],
        )
        self.assertEqual([command.advisory for command in facts.of(Command)][:3], ["", "", "|| true"])
        self.assertEqual(next(iter(facts.of(CiJob))).env["LEIN_ROOT"], "true")
        self.assertEqual(list(facts.of(Unknown)), [])

    def test_named_tasks_each_on_their_own_instance(self) -> None:
        facts = _facts(NAMED)
        self.assertEqual(
            _jobs(facts),
            [
                (".cirrus.yml:lint", "lint", "linux", "python:3.12"),
                (".cirrus.yml:Windows tests", "Windows tests", "windows", "cirrusci/windowsservercore:2019"),
                (".cirrus.yml:freebsd", "freebsd", "freebsd", None),
                (".cirrus.yml:mac", "mac", "linux", None),
                (".cirrus.yml:win", "win", "windows", None),
            ],
        )
        self.assertEqual(
            argvs(facts),
            [
                ("ruff", "check", "."),
                ("mypy", "."),
                ("pytest",),
                ("tee", "log"),
                ("pytest", "-k", "'not", "slow'"),
                ("python$PY", "-m", "pytest"),
                ("pytest",),
                ("docker", "build", "."),
                ("docker", "build", "."),
            ],
        )
        # A Unix script runs under `set -e` and `set -o pipefail`: a pipeline's failure fails the task.
        self.assertEqual({command.advisory for command in facts.of(Command)}, {""})
        self.assertEqual([command.job for command in facts.of(Command)][4], ".cirrus.yml:Windows tests")

    def test_tasks_written_under_the_same_key_are_each_read(self) -> None:
        task = "task:\n  name: {}\n  container: {{image: rust}}\n  script: cargo {}\n"
        text = task.format("one", "test") + task.format("two", "clippy")
        facts = _facts(text)
        self.assertEqual([job.name for job in facts.of(CiJob)], ["one", "two"])
        self.assertEqual(argvs(facts), [("cargo", "test"), ("cargo", "clippy")])
        unnamed = "task:\n  script: make\ntask:\n  script: make check\n"
        self.assertEqual([job.id for job in _facts(unnamed).of(CiJob)], [".cirrus.yml:main", ".cirrus.yml:main[2]"])

    def test_each_leg_of_a_matrix_is_a_task(self) -> None:
        text = """\
test_task:
  container: {image: python}
  env: {CI: "1"}
  matrix:
    - name: py311
      env: {PY: "3.11"}
    - name: py312
      env: {PY: "3.12"}
      container: {image: python:3.12}
  script: python$PY -m pytest
"""
        facts = _facts(text)
        self.assertEqual(
            _jobs(facts),
            [
                (".cirrus.yml:py311", "py311", "linux", "python"),
                (".cirrus.yml:py312", "py312", "linux", "python:3.12"),
            ],
        )
        self.assertEqual([job.env for job in facts.of(CiJob)], [{"CI": "1", "PY": "3.11"}, {"CI": "1", "PY": "3.12"}])
        self.assertEqual({command.job for command in facts.of(Command)}, {".cirrus.yml:py311", ".cirrus.yml:py312"})

    def test_a_script_that_cannot_fail_the_task(self) -> None:
        text = """\
task:
  container: {image: node}
  allow_failures: true
  test_script: npm test
lint_task:
  container: {image: node}
  server_background_script: npm start
  lint_script: npm run lint
"""
        advisories = {command.argv: command.advisory for command in _facts(text).of(Command)}
        self.assertEqual(
            advisories,
            {
                ("npm", "test"): "allow_failures",
                ("npm", "start"): "it runs in the background",
                ("npm", "run", "lint"): "",
            },
        )

    def test_a_task_on_an_instance_of_unknown_os(self) -> None:
        """Its own instance wins over the one written at the top."""
        text = "container: {image: gcc}\ntask:\n  persistent_worker:\n    labels: {name: box}\n  script: make check\n"
        self.assertEqual(_jobs(_facts(text)), [(".cirrus.yml:main", "main", "unknown", None)])

    def test_the_top_merges_a_mapping_in(self) -> None:
        text = "base: &base\n  container: {image: gcc}\n<<: *base\ntask:\n  script: make\n"
        self.assertEqual(_jobs(_facts(text)), [(".cirrus.yml:main", "main", "linux", "gcc")])
