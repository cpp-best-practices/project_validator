"""Every reader that follows a chain (includes, templates, references, reusable workflows, nested calls, extended
configurations) stops at its limit, and is tested exactly there: the chain at the limit is followed, and one past it
is not, with an unknown that says why rather than a silent cut-off (upstream #303)."""

from __future__ import annotations

import json
import unittest
from collections.abc import Callable, Mapping

from project_validator.build_systems import cmake
from project_validator.ecosystems.javascript.analysis import _strict_settings
from project_validator.facts import Command, Fact, Facts, Unknown
from project_validator.facts.build import CompilerOption
from project_validator.limits import (
    BAZELRC_IMPORTS,
    CMAKE_NESTING,
    COMPOSITE_ACTIONS,
    GITLAB_EXTENDS,
    GITLAB_INCLUDES,
    GITLAB_REFERENCES,
    MAKE_INCLUDES,
    REUSABLE_WORKFLOWS,
    TSCONFIG_EXTENDS,
    Limit,
)
from tests.support import github_job, make_context, temp_project

type Files = dict[str, str]


def _facts(files: Mapping[str, str]) -> Facts:
    with temp_project(dict(files)) as root:
        return make_context(root).facts


def _commands(facts: Facts) -> list[tuple[str, ...]]:
    return [command.argv for command in facts.of(Command)]


def _reasons(found: Facts | tuple[Fact, ...]) -> list[str]:
    facts = found.of(Unknown) if isinstance(found, Facts) else (fact for fact in found if isinstance(fact, Unknown))
    return [fact.reason for fact in facts]


class LimitTestCase(unittest.TestCase):
    def assert_limit(self, limit: Limit, chain: Callable[[int], Files], followed: Callable[[Files], bool]) -> None:
        """A chain `limit` long is followed, and one a link longer is not."""
        self.assertTrue(followed(chain(limit.most)), f"a chain of {limit.most} is not followed")
        self.assertFalse(followed(chain(limit.most + 1)), f"a chain of {limit.most + 1} is followed")


class GitlabLimitTests(LimitTestCase):
    @staticmethod
    def _includes(levels: int) -> Files:
        files = {".gitlab-ci.yml": "include:\n  - local: a1.yml\n"}
        for level in range(1, levels):
            files[f"a{level}.yml"] = f"include:\n  - local: a{level + 1}.yml\n"
        files[f"a{levels}.yml"] = "deep:\n  script: [ctest]\n"
        return files

    @staticmethod
    def _extends(levels: int) -> Files:
        text = "job:\n  extends: .t1\n"
        text += "".join(f".t{level}:\n  extends: .t{level + 1}\n" for level in range(1, levels))
        return {".gitlab-ci.yml": text + f".t{levels}:\n  script: [ctest]\n"}

    @staticmethod
    def _references(levels: int) -> Files:
        text = ".r1:\n  script: [ctest]\n"
        text += "".join(
            f".r{level}:\n  script: [!reference [.r{level - 1}, script]]\n" for level in range(2, levels + 1)
        )
        return {".gitlab-ci.yml": text + f"job:\n  script: [!reference [.r{levels}, script]]\n"}

    def test_includes_nest_at_most_the_limit_deep(self) -> None:
        self.assert_limit(GITLAB_INCLUDES, self._includes, lambda files: ("ctest",) in _commands(_facts(files)))
        self.assertIn(GITLAB_INCLUDES.reason, _reasons(_facts(self._includes(GITLAB_INCLUDES.most + 1))))

    def test_an_include_back_into_the_chain_is_a_cycle_not_a_chain_too_deep(self) -> None:
        files = {".gitlab-ci.yml": "include:\n  - local: a.yml\n", "a.yml": "include:\n  - local: .gitlab-ci.yml\n"}
        self.assertEqual(_reasons(_facts(files)), [".gitlab-ci.yml includes itself, through .gitlab-ci.yml → a.yml"])

    def test_extends_nest_at_most_the_limit_deep(self) -> None:
        self.assert_limit(GITLAB_EXTENDS, self._extends, lambda files: ("ctest",) in _commands(_facts(files)))

    def test_extends_past_the_limit_say_so(self) -> None:
        reasons = _reasons(_facts(self._extends(GITLAB_EXTENDS.most + 1)))
        self.assertEqual(reasons, ["the templates it extends nest more than 10 levels deep"])

    def test_references_nest_at_most_the_limit_deep(self) -> None:
        self.assert_limit(GITLAB_REFERENCES, self._references, lambda files: ("ctest",) in _commands(_facts(files)))

    def test_references_past_the_limit_say_so(self) -> None:
        reasons = _reasons(_facts(self._references(GITLAB_REFERENCES.most + 1)))
        self.assertEqual(reasons, ["its !reference tags nest more than 10 levels deep"])


class BazelLimitTests(LimitTestCase):
    @staticmethod
    def _imports(levels: int) -> Files:
        files = {"MODULE.bazel": "", ".bazelrc": "import %workspace%/r1.bazelrc\n"}
        for level in range(1, levels):
            files[f"r{level}.bazelrc"] = f"import %workspace%/r{level + 1}.bazelrc\n"
        files[f"r{levels}.bazelrc"] = "build --copt=-Werror\n"
        return {**files, **github_job("ubuntu-latest", "bazel build //...")}

    def test_rc_files_import_each_other_at_most_the_limit_deep(self) -> None:
        self.assert_limit(
            BAZELRC_IMPORTS,
            self._imports,
            lambda files: any("--copt=-Werror" in argv for argv in _commands(_facts(files))),
        )


class GithubLimitTests(LimitTestCase):
    @staticmethod
    def _calls(levels: int) -> Files:
        files = {".github/workflows/ci.yml": "on: push\njobs:\n  c:\n    uses: ./.github/workflows/w1.yml\n"}
        for level in range(1, levels):
            files[f".github/workflows/w{level}.yml"] = (
                f"on: workflow_call\njobs:\n  c:\n    uses: ./.github/workflows/w{level + 1}.yml\n"
            )
        steps = "    runs-on: ubuntu-latest\n    steps:\n      - run: ctest\n"
        files[f".github/workflows/w{levels}.yml"] = "on: workflow_call\njobs:\n  t:\n" + steps
        return files

    def test_reusable_workflows_call_each_other_at_most_the_limit_deep(self) -> None:
        self.assert_limit(REUSABLE_WORKFLOWS, self._calls, lambda files: ("ctest",) in _commands(_facts(files)))
        limit = REUSABLE_WORKFLOWS.most
        reasons = _reasons(_facts(self._calls(limit + 1)))
        self.assertEqual(reasons, [REUSABLE_WORKFLOWS.reason])

    def test_a_reusable_workflow_that_calls_itself_is_a_cycle(self) -> None:
        files = self._calls(1)
        files[".github/workflows/w1.yml"] = "on: workflow_call\njobs:\n  c:\n    uses: ./.github/workflows/w1.yml\n"
        self.assertEqual(
            _reasons(_facts(files)),
            [".github/workflows/w1.yml calls itself, through .github/workflows/ci.yml → .github/workflows/w1.yml"],
        )

    @staticmethod
    def _actions(levels: int) -> Files:
        steps = "    runs-on: ubuntu-latest\n    steps:\n      - uses: ./a1\n"
        files = {".github/workflows/ci.yml": "on: push\njobs:\n  t:\n" + steps}
        for level in range(1, levels):
            files[f"a{level}/action.yml"] = f"runs:\n  using: composite\n  steps:\n    - uses: ./a{level + 1}\n"
        files[f"a{levels}/action.yml"] = "runs:\n  using: composite\n  steps:\n    - run: ctest\n      shell: bash\n"
        return files

    def test_composite_actions_use_each_other_at_most_the_limit_deep(self) -> None:
        self.assert_limit(COMPOSITE_ACTIONS, self._actions, lambda files: ("ctest",) in _commands(_facts(files)))

    def test_composite_actions_past_the_limit_say_so(self) -> None:
        reasons = _reasons(_facts(self._actions(COMPOSITE_ACTIONS.most + 1)))
        self.assertEqual(reasons, ["the composite actions it uses nest more than 4 levels deep"])

    def test_a_composite_action_that_uses_itself_is_a_cycle(self) -> None:
        files = self._actions(1)
        files["a1/action.yml"] = "runs:\n  using: composite\n  steps:\n    - uses: ./a1\n"
        self.assertEqual(
            _reasons(_facts(files)), ["a1/action.yml uses itself, through .github/workflows/ci.yml → a1/action.yml"]
        )


class TsconfigLimitTests(LimitTestCase):
    @staticmethod
    def _extends(levels: int) -> Files:
        files = {"tsconfig.json": json.dumps({"extends": "./tsconfig.b1"}), "src/a.ts": "export const a = 1;\n"}
        for level in range(1, levels):
            files[f"tsconfig.b{level}.json"] = json.dumps({"extends": f"./tsconfig.b{level + 1}"})
        files[f"tsconfig.b{levels}.json"] = json.dumps({"compilerOptions": {"strict": True}})
        return files

    def test_a_configuration_extends_local_bases_at_most_the_limit_deep(self) -> None:
        self.assert_limit(
            TSCONFIG_EXTENDS, self._extends, lambda files: bool(_strict_settings("tsconfig.json", _facts(files)))
        )


class MakeLimitTests(LimitTestCase):
    @staticmethod
    def _includes(levels: int) -> Files:
        """A Makefile that includes 1.mk, which includes 2.mk, … `levels` deep; the deepest defines `lint`."""
        files = {"Makefile": "include 1.mk\n"}
        files |= {f"{level}.mk": f"include {level + 1}.mk\n" for level in range(1, levels)}
        files[f"{levels}.mk"] = "lint:\n\tdeep-lint .\n"
        return {**files, **github_job("ubuntu-latest", "make lint")}

    def test_includes_nest_at_most_the_limit_deep(self) -> None:
        self.assert_limit(MAKE_INCLUDES, self._includes, lambda files: ("deep-lint", ".") in _commands(_facts(files)))

    def test_includes_past_the_limit_say_so(self) -> None:
        self.assertIn(MAKE_INCLUDES.reason, _reasons(_facts(self._includes(MAKE_INCLUDES.most + 1))))


class CmakeLimitTests(LimitTestCase):
    @staticmethod
    def _calls(levels: int) -> Files:
        functions = "".join(f"function(f{level})\n  f{level + 1}()\nendfunction()\n" for level in range(1, levels))
        last = f"function(f{levels})\n  add_compile_options(-deep)\nendfunction()\nf1()\n"
        return {"CMakeLists.txt": functions + last}

    @staticmethod
    def _evaluated(files: Files) -> tuple[Fact, ...]:
        return cmake._evaluated(files).facts

    def test_functions_call_each_other_at_most_the_limit_deep(self) -> None:
        found = self._evaluated(self._calls(CMAKE_NESTING.most))
        self.assertIn("-deep", [fact.option for fact in found if isinstance(fact, CompilerOption)])
        self.assertEqual(_reasons(found), [])

    def test_calls_past_the_limit_say_so(self) -> None:
        for levels in (CMAKE_NESTING.most + 1, CMAKE_NESTING.most + 2):
            with self.subTest(levels=levels):
                self.assertEqual(
                    _reasons(self._evaluated(self._calls(levels))),
                    ["calls, includes or subdirectories nest more than 24 levels deep"],
                )


class LimitTests(unittest.TestCase):
    def test_a_limit_says_how_deep_it_follows(self) -> None:
        limit = Limit("its includes", 3)
        self.assertEqual([limit.allows(levels) for levels in (2, 3, 4)], [True, True, False])
        self.assertEqual(limit.reason, "its includes nest more than 3 levels deep")


if __name__ == "__main__":
    unittest.main()
