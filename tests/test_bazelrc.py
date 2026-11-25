"""`.bazelrc`: a bazel command runs with the options its workspace's rc files give it, written out, so that what they
set (`--copt=-Werror`, `-c opt`) is seen as the command's own (upstream #207)."""

from __future__ import annotations

import json
import unittest

from project_validator.build_systems.bazel.build import BAZEL
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Status
from project_validator.facts import Command, Facts
from tests.support import GITHUB_WORKFLOW, github_job, make_context, temp_project

CXX = {"MODULE.bazel": 'module(name = "app")\n', "BUILD.bazel": 'cc_test(name = "t", srcs = ["t.cc"])\n', "t.cc": ""}

# googletest's: configs named on the command line, one bringing another.
GOOGLETEST_RC = """\
# Comments and blank lines are passed over.

common --show_timestamps
build --copt=-Wextra
test --test_output=errors
build:linux --cxxopt=-std=c++17 --host_cxxopt=-std=c++17
build:linux --copt=-Wall
build:linux --copt=-Werror
build:gcc --config=linux --platforms=//ci:linux_gcc
build:windows-msvc --copt=/WX
"""

# Catch2's: the config named for the host's OS applies by itself.
CATCH2_RC = """\
build --enable_platform_specific_config
build:linux --config=gcc11
build:gcc11 --cxxopt=-std=c++2a
build:windows --copt=/WX
"""


def _facts(files: dict[str, str]) -> Facts:
    with temp_project({**CXX, **files}) as root:
        return make_context(root).facts


def _expanded(facts: Facts) -> list[tuple[str, ...]]:
    return [command.argv for command in facts.of(Command) if "--ignore_all_rc_files" in command.argv]


class BazelrcTests(unittest.TestCase):
    def test_a_command_takes_the_options_of_its_commands_and_configs(self) -> None:
        facts = _facts({".bazelrc": GOOGLETEST_RC, **github_job("ubuntu-latest", "bazel test --config gcc //...")})
        self.assertEqual(
            _expanded(facts),
            [
                (
                    *("bazel", "--ignore_all_rc_files", "test", "--show_timestamps", "--copt=-Wextra"),
                    *("--test_output=errors", "--cxxopt=-std=c++17", "--host_cxxopt=-std=c++17", "--copt=-Wall"),
                    *("--copt=-Werror", "--platforms=//ci:linux_gcc", "//..."),
                )
            ],
        )
        # A build takes neither the test command's options nor a config it is not given.
        facts = _facts({".bazelrc": GOOGLETEST_RC, **github_job("ubuntu-latest", "bazelisk build //...")})
        self.assertEqual(
            _expanded(facts),
            [("bazelisk", "--ignore_all_rc_files", "build", "--show_timestamps", "--copt=-Wextra", "//...")],
        )

    def test_what_the_options_set_is_the_commands_own(self) -> None:
        workflow = github_job("ubuntu-latest", "bazel test --config=gcc //...")
        with temp_project({**CXX, ".bazelrc": GOOGLETEST_RC, **workflow}) as root:
            self.assertEqual(warnings_as_errors.run(make_context(root)).status, Status.PASS)
        with temp_project(
            {**CXX, ".bazelrc": GOOGLETEST_RC, **github_job("ubuntu-latest", "bazel test //...")}
        ) as root:
            self.assertEqual(warnings_as_errors.run(make_context(root)).status, Status.FAIL)
        facts = _facts({".bazelrc": "build -c opt\n", **github_job("ubuntu-latest", "bazel build //...")})
        [expanded] = (command for command in facts.of(Command) if "--ignore_all_rc_files" in command.argv)
        self.assertEqual(BAZEL.build_types(expanded), {"release"})  # type: ignore[misc]

    def test_the_config_of_the_hosts_os_applies_where_it_is_enabled(self) -> None:
        for runner, expected in (
            ("ubuntu-latest", ("--enable_platform_specific_config", "--cxxopt=-std=c++2a")),
            ("windows-latest", ("--enable_platform_specific_config", "--copt=/WX")),
            ("macos-latest", ("--enable_platform_specific_config",)),
        ):
            with self.subTest(runner=runner):
                facts = _facts({".bazelrc": CATCH2_RC, **github_job(runner, "bazel build //...")})
                self.assertEqual(_expanded(facts), [("bazel", "--ignore_all_rc_files", "build", *expected, "//...")])

    def test_the_config_of_the_hosts_os_applies_only_while_it_is_enabled(self) -> None:
        for disabled in ("build --enable_platform_specific_config=false", "build --noenable_platform_specific_config"):
            with self.subTest(disabled=disabled):
                facts = _facts(
                    {".bazelrc": CATCH2_RC + disabled + "\n", **github_job("windows-latest", "bazel build //...")}
                )
                [expanded] = _expanded(facts)
                self.assertNotIn("--copt=/WX", expanded)

    def test_a_command_in_a_directory_of_the_workspace_reads_the_workspaces_rc_file(self) -> None:
        step = {"run": "bazel build //...", "working-directory": "pkg"}
        workflow = {"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": [step]}}}
        files = {".bazelrc": "build --copt=-Werror\n", "pkg/BUILD.bazel": "", GITHUB_WORKFLOW: json.dumps(workflow)}
        self.assertEqual(
            _expanded(_facts(files)), [("bazel", "--ignore_all_rc_files", "build", "--copt=-Werror", "//...")]
        )

    def test_imports_in_the_workspace_are_followed(self) -> None:
        files = {
            ".bazelrc": "import %workspace%/tools/ci.bazelrc\ntry-import %workspace%/user.bazelrc\n",
            "tools/ci.bazelrc": "build --copt=-Werror \\\n  --copt=-Wall\nbuild --copt=-Wextra \\",
            **github_job("ubuntu-latest", "bazel build //..."),
        }
        self.assertEqual(
            _expanded(_facts(files)),
            [("bazel", "--ignore_all_rc_files", "build", "--copt=-Werror", "--copt=-Wall", "--copt=-Wextra", "//...")],
        )

    def test_an_rc_file_the_command_names_is_read_after_the_workspaces(self) -> None:
        files = {".bazelrc": "build --copt=-Wall\n", "ci/ci.bazelrc": "build --copt=-Werror\n"}
        facts = _facts({**files, **github_job("ubuntu-latest", "bazel --bazelrc=ci/ci.bazelrc build //...")})
        self.assertEqual(
            _expanded(facts),
            [
                (
                    "bazel",
                    "--bazelrc=ci/ci.bazelrc",
                    "--ignore_all_rc_files",
                    "build",
                    "--copt=-Wall",
                    "--copt=-Werror",
                    "//...",
                )
            ],
        )

    def test_nothing_is_expanded_without_options_or_where_rc_files_are_ignored(self) -> None:
        ignoring = ("bazel", "--ignore_all_rc_files", "build", "//...")
        for files, expected in (
            (github_job("ubuntu-latest", "bazel build //..."), []),
            # Only a config the command is not given, and startup options.
            (
                {
                    ".bazelrc": "build:other --copt=-Wall\nstartup --batch\n",
                    **github_job("ubuntu-latest", "bazel build //..."),
                },
                [],
            ),
            # The command's own, not expanded again.
            ({".bazelrc": "build --copt=-Wall\n", **github_job("ubuntu-latest", " ".join(ignoring))}, [ignoring]),
        ):
            with self.subTest(files=files):
                self.assertEqual(_expanded(_facts(files)), expected)

    def test_configs_that_bring_each_other_end(self) -> None:
        rc = "build:a --config=b --copt=-Wall\nbuild:b --config=a --copt=-Werror\n"
        facts = _facts({".bazelrc": rc, **github_job("ubuntu-latest", "bazel build --config=a //...")})
        self.assertEqual(
            _expanded(facts), [("bazel", "--ignore_all_rc_files", "build", "--copt=-Werror", "--copt=-Wall", "//...")]
        )
