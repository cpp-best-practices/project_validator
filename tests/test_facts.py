"""The fact database: the facts CI configuration yields, and how shell scripts are split into commands."""

import json
import unittest

from project_validator.ci.github_actions import EXPRESSION
from project_validator.facts import ActionStep, CiJob, Command, Facts, Origin, Unknown, as_dict
from project_validator.facts.shell import ShellCommand, Unsplittable, split_script
from tests.support import GITHUB_WORKFLOW, make_context, temp_project


def _facts(files: dict[str, str]) -> Facts:
    with temp_project(files) as root:
        return make_context(root).facts


def _argvs(facts: Facts) -> list[tuple[str, ...]]:
    return [command.argv for command in facts.of(Command)]


class ShellTests(unittest.TestCase):
    def _split(self, script: str) -> list[tuple[str, ...]]:
        return [found.argv for found in split_script(script) if isinstance(found, ShellCommand)]

    def test_operators_separate_commands_and_continuations_join_lines(self) -> None:
        script = "cmake -S . -B build && cmake --build build \\\n  --config Release\nctest || exit 1; echo ok | tee x\n"
        self.assertEqual(
            self._split(script),
            [
                ("cmake", "-S", ".", "-B", "build"),
                ("cmake", "--build", "build", "--config", "Release"),
                ("ctest",),
                ("exit", "1"),
                ("echo", "ok"),
                ("tee", "x"),
            ],
        )

    def test_quotes_comments_and_redirections(self) -> None:
        script = (
            "gcovr --gcov-executable 'llvm-cov gcov' -DX=\"a b\" # coverage\nmake 2>&1 > log.txt\n# only a comment\n"
        )
        self.assertEqual(self._split(script), [("gcovr", "--gcov-executable", "llvm-cov gcov", "-DX=a b"), ("make",)])

    def test_assignments_are_the_commands_environment(self) -> None:
        [found] = split_script("CC=gcc-14 CXX=g++-14 cmake -S .")
        self.assertEqual(
            found,
            ShellCommand(
                argv=("cmake", "-S", "."),
                env=(("CC", "gcc-14"), ("CXX", "g++-14")),
                line="CC=gcc-14 CXX=g++-14 cmake -S .",
            ),
        )

    def test_compound_command_keywords_are_not_commands(self) -> None:
        script = "if [ -f x ]; then ctest; fi\nfor f in a b; do echo $f; done\n"
        self.assertEqual(
            self._split(script), [("[", "-f", "x", "]"), ("ctest",), ("for", "f", "in", "a", "b"), ("echo", "$f")]
        )

    def test_opaque_text_keeps_its_quotes(self) -> None:
        [found] = split_script("""echo "a ${{ x == 'y' }}" '${{ z }}'""", EXPRESSION)
        self.assertEqual(found, ShellCommand(argv=("echo", "a ${{ x == 'y' }}", "${{ z }}"), env=(), line=found.line))
        [unsplittable] = split_script("echo ${{ 'a' }} 'open", EXPRESSION)
        self.assertEqual(unsplittable, Unsplittable(line="echo ${{ 'a' }} 'open", reason="No closing quotation"))

    def test_an_unbalanced_quote_cannot_be_split(self) -> None:
        self.assertEqual(
            list(split_script('echo "open')), [Unsplittable(line='echo "open', reason="No closing quotation")]
        )


class GitHubActionsFactTests(unittest.TestCase):
    WORKFLOW = """\
        env:
          GLOBAL: "1"
        jobs:
          test:
            runs-on: ${{ matrix.os }}
            env:
              CC: ${{ matrix.cc }}
            strategy:
              matrix:
                os: [ubuntu-latest, windows-latest]
                cc: [gcc]
            steps:
              - uses: actions/checkout@v4
              - uses: aminya/setup-cpp@v1
                with:
                  compiler: ${{ matrix.cc }}
              - name: test
                if: runner.os != 'Windows'
                working-directory: build
                run: |
                  cmake -S .. -B . && ctest -C Debug
          container-job:
            runs-on: ubuntu-latest
            container: python:3.14
            steps:
              - run: python -m unittest
          computed:
            strategy:
              matrix: ${{ fromJSON(needs.setup.outputs.matrix) }}
            runs-on: ubuntu-latest
          reuse:
            uses: org/repo/.github/workflows/build.yml@v1
        """

    def setUp(self) -> None:
        self.facts = _facts({GITHUB_WORKFLOW: self.WORKFLOW})

    def test_each_matrix_combination_is_a_job(self) -> None:
        jobs = {job.id: job for job in self.facts.of(CiJob)}
        self.assertEqual(
            list(jobs), [f"{GITHUB_WORKFLOW}:test[0]", f"{GITHUB_WORKFLOW}:test[1]", f"{GITHUB_WORKFLOW}:container-job"]
        )
        first = jobs[f"{GITHUB_WORKFLOW}:test[0]"]
        self.assertEqual(
            (first.os, dict(first.matrix), dict(first.env)),
            ("linux", {"os": "ubuntu-latest", "cc": "gcc"}, {"GLOBAL": "1", "CC": "gcc"}),
        )
        self.assertEqual(jobs[f"{GITHUB_WORKFLOW}:test[1]"].os, "windows")
        self.assertEqual(jobs[f"{GITHUB_WORKFLOW}:container-job"].image, "python:3.14")

    def test_commands_carry_their_step_and_condition(self) -> None:
        commands = [command for command in self.facts.of(Command) if command.job.endswith("test[0]")]
        self.assertEqual(
            [command.argv for command in commands], [("cmake", "-S", "..", "-B", "."), ("ctest", "-C", "Debug")]
        )
        self.assertEqual(
            (str(commands[0].origin), commands[0].directory, commands[0].condition, commands[0].env["CC"]),
            (f"{GITHUB_WORKFLOW}:jobs.test.steps[2].run", "build", "runner.os != 'Windows'", "gcc"),
        )

    def test_actions_carry_their_inputs(self) -> None:
        steps = [step for step in self.facts.of(ActionStep) if step.job.endswith("test[1]")]
        self.assertEqual([step.uses for step in steps], ["actions/checkout@v4", "aminya/setup-cpp@v1"])
        self.assertEqual(dict(steps[1].inputs), {"compiler": "gcc"})

    def test_expressions_are_evaluated_by_github_before_the_shell_splits_the_line(self) -> None:
        workflow = """\
            jobs:
              build:
                strategy:
                  matrix:
                    type: [Debug]
                    include:
                      - type: Release
                        generator: TBZ2
                runs-on: ubuntu-latest
                steps:
                  - run: cmake -DCOVERAGE=${{ matrix.type == 'Debug' }} && cpack -G ${{ matrix.generator }}
            """
        commands = _facts({GITHUB_WORKFLOW: workflow}).of(Command)
        self.assertEqual(
            [command.argv for command in commands],
            [
                ("cmake", "-DCOVERAGE=${{ matrix.type == 'Debug' }}"),
                ("cpack", "-G"),  # a key the combination lacks is empty
                ("cmake", "-DCOVERAGE=${{ matrix.type == 'Debug' }}"),
                ("cpack", "-G", "TBZ2"),
            ],
        )

    def test_what_cannot_be_read_is_unknown(self) -> None:
        unknown = {fact.subject: fact.reason for fact in self.facts.of(Unknown)}
        self.assertEqual(
            unknown,
            {
                "the matrix of job computed": "it is computed by an expression",
                "job reuse": (
                    "it calls the reusable workflow org/repo/.github/workflows/build.yml@v1, which is not read"
                ),
            },
        )


class GitLabFactTests(unittest.TestCase):
    PIPELINE = """\
        image: gcc:14
        variables:
          GLOBAL: "1"
        default:
          before_script:
            - apt-get update
        build:
          variables:
            BUILD_TYPE: Release
          parallel:
            matrix:
              - CXX: [g++, clang++]
          script:
            - cmake -S . -B build -DCMAKE_CXX_COMPILER=$CXX
        mac:
          tags: [macos]
          extends: .template
          script: ctest
        .template:
          script: never
        """

    def setUp(self) -> None:
        self.facts = _facts({".gitlab-ci.yml": self.PIPELINE})

    def test_parallel_matrix_combinations_are_jobs_with_variables(self) -> None:
        jobs = self.facts.of(CiJob)
        self.assertEqual(
            [job.id for job in jobs], [".gitlab-ci.yml:build[0]", ".gitlab-ci.yml:build[1]", ".gitlab-ci.yml:mac"]
        )
        self.assertEqual(dict(jobs[1].env), {"GLOBAL": "1", "BUILD_TYPE": "Release", "CXX": "clang++"})
        # Only Linux runners run jobs in Docker images.
        self.assertEqual(
            [(job.os, job.image) for job in jobs], [("linux", "gcc:14"), ("linux", "gcc:14"), ("macos", None)]
        )

    def test_default_scripts_run_before_the_jobs_own(self) -> None:
        self.assertEqual(
            _argvs(self.facts),
            [
                ("apt-get", "update"),
                ("cmake", "-S", ".", "-B", "build", "-DCMAKE_CXX_COMPILER=g++"),
                ("apt-get", "update"),
                ("cmake", "-S", ".", "-B", "build", "-DCMAKE_CXX_COMPILER=clang++"),
                ("apt-get", "update"),
                ("ctest",),
            ],
        )
        self.assertEqual(str(self.facts.of(Command)[0].origin), ".gitlab-ci.yml:default.before_script[0]")

    def test_extends_is_not_resolved(self) -> None:
        self.assertEqual(
            self.facts.of(Unknown),
            (
                Unknown(
                    origin=Origin(path=".gitlab-ci.yml", at=("mac",)),
                    subject="job mac",
                    reason="extends: is not resolved",
                ),
            ),
        )


class OtherProviderFactTests(unittest.TestCase):
    def test_unparsed_configuration_is_a_heuristic_job_with_unknown_commands(self) -> None:
        facts = _facts({".travis.yml": "script: make\n"})
        [job] = facts.of(CiJob)
        self.assertTrue(job.heuristic)
        self.assertEqual(facts.of(Unknown)[0].reason, "Travis CI configuration is not parsed")

    def test_malformed_documents_yield_what_they_can(self) -> None:
        workflow = "jobs:\n  odd: text\n  build:\n    runs-on: ubuntu-latest\n    steps: [text, {run: ctest}]\n"
        facts = _facts({GITHUB_WORKFLOW: workflow, ".github/workflows/list.yml": "- a\n", ".gitlab-ci.yml": "- a\n"})
        self.assertEqual(_argvs(facts), [("ctest",)])
        self.assertEqual([type(fact) for fact in facts], [CiJob, Command])

    def test_invalid_yaml_is_unknown(self) -> None:
        facts = _facts({GITHUB_WORKFLOW: "jobs: [\n"})
        self.assertEqual(len(facts), 1)
        self.assertIn("invalid YAML", facts.of(Unknown)[0].reason)

    def test_a_line_that_cannot_be_split_is_unknown(self) -> None:
        facts = _facts({".gitlab-ci.yml": 'build:\n  script:\n    - echo "open\n'})
        self.assertEqual(facts.of(Unknown)[0].subject, "the command 'echo \"open'")


class SerialisationTests(unittest.TestCase):
    def test_a_fact_is_its_kind_and_fields(self) -> None:
        command = Command(
            origin=Origin(path="ci.yml", at=("jobs", "a", "steps", 0, "run")),
            job="ci.yml:a",
            argv=("make",),
            line="make",
        )
        self.assertEqual(
            as_dict(command),
            {
                "kind": "Command",
                "origin": "ci.yml:jobs.a.steps[0].run",
                "job": "ci.yml:a",
                "argv": ["make"],
                "line": "make",
                "env": {},
                "directory": None,
                "condition": None,
                "via": [],
            },
        )
        self.assertEqual(str(Origin(path="ci.yml")), "ci.yml")
        json.dumps(Facts((command,)).as_dicts())
