"""Commands that run what the checkout does not show (a script a step writes, an Earthly target), recorded as
unknown so that a strict run says so instead of a confident answer, and a command run in a container image, read
as a command of the job (#195)."""

from __future__ import annotations

import unittest

from project_validator.facts import Command, Unknown, resolved
from tests.support import github_steps, make_context, temp_project


def _commands(*steps: str) -> list[tuple[str, ...]]:
    with temp_project(github_steps(*steps)) as root:
        return [resolved(command) for command in make_context(root).facts.of(Command)]


def _unknowns(*steps: str, files: dict[str, str] | None = None) -> list[Unknown]:
    with temp_project({**(files or {}), **github_steps(*steps)}) as root:
        return [unknown for unknown in make_context(root).facts.of(Unknown) if unknown.hides == "commands"]


class MissingScriptTests(unittest.TestCase):
    def test_a_shell_script_not_in_the_repository_is_unknown(self) -> None:
        """geerlingguy/ansible-for-devops downloads tests/test.sh in one step and runs it in the next."""
        [unknown] = _unknowns("run: curl -o ci/test.sh https://example.com/x", "run: ci/test.sh")
        self.assertEqual(unknown.subject, "the script ci/test.sh")
        self.assertIn("not in the repository", unknown.reason)

    def test_a_program_the_build_makes_is_not_a_missing_script(self) -> None:
        for line in (
            "run: ./build/app --selftest",
            "run: bin/tool",
            "run: '\"bash -x ./ci/test.sh\"'",
            "run: sh scripts/*.sh",
            "run: sh ':(exclude)tests/license.sh'",
        ):
            with self.subTest(line=line):
                self.assertEqual(_unknowns(line), [])

    def test_a_script_that_is_there_is_read(self) -> None:
        files = {"ci/test.sh": "#!/bin/sh\npytest\n"}
        self.assertEqual(_unknowns("run: ci/test.sh", files=files), [])


class DockerRunTests(unittest.TestCase):
    """`docker run IMAGE COMMAND` runs COMMAND in the image: it is read as a command of the job, as a launcher's is."""

    def test_the_command_run_in_a_container_image_is_read(self) -> None:
        for line, inner in (
            ('run: docker run --rm -v "$PWD:/doc" img ruff check .', ("ruff", "check", ".")),
            ('run: docker run -e "CI=$CI" -itv "$PWD":/code bats:test bats test/', ("bats", "test/")),
            ('run: docker run -itv "$PWD":/code --entrypoint bash bats:test test.sh', ("bash", "test.sh")),
            ("run: docker run --rm ${{ steps.vars.outputs.image }} ruff check .", ("ruff", "check", ".")),
        ):
            with self.subTest(line=line):
                self.assertIn(inner, _commands(line))

    def test_the_variables_it_passes_are_the_commands(self) -> None:
        with temp_project(github_steps("run: docker run -e RUFF_OUTPUT_FORMAT=github img ruff check .")) as root:
            facts = make_context(root).facts
        [command] = [command for command in facts.of(Command) if command.argv[:1] == ("ruff",)]
        self.assertEqual(command.env.get("RUFF_OUTPUT_FORMAT"), "github")

    def test_a_container_started_without_a_command_runs_nothing_more(self) -> None:
        for line in (
            "run: docker run -d -p 5432:5432 postgres:16",
            "run: docker run --rm hello-world",
            # Options of the image's own program (its entrypoint), not a command of their own.
            'run: docker run -it "bash:5" --version',
            "run: docker run --rm multiarch/qemu-user-static --reset -p yes",
        ):
            with self.subTest(line=line):
                self.assertEqual([argv for argv in _commands(line) if argv[0] != "docker"], [])


class EarthlyTests(unittest.TestCase):
    def test_an_earthly_target_is_unknown(self) -> None:
        """elixir-ecto/ecto's integration tests run under `earthly +integration-test`."""
        files = {"Earthfile": "test:\n  RUN mix test\n"}
        [unknown] = _unknowns("run: earthly -P --ci +test", files=files)
        self.assertEqual(unknown.subject, "the Earthly target +test")
