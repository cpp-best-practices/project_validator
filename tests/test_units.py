"""Monorepos and mixed-language projects: the units of a project, and questions answered unit by unit."""

from __future__ import annotations

import json
import unittest

from project_validator.checks.coverage import coverage
from project_validator.cli import EXIT_FAILURE, EXIT_USAGE
from project_validator.core import Placed, Result, Status
from project_validator.facts import CiJob, Command, Unknown
from project_validator.facts.auxiliary import Selectors
from project_validator.facts.structure import Unit
from project_validator.grid import MARKS
from project_validator.questions.analysis import static_analysis
from tests.support import GITHUB_WORKFLOW, checks_named, make_context, temp_project
from tests.test_cli import run_cli


def _workflow(*steps: tuple[str, str | None]) -> dict[str, str]:
    """A GitHub workflow running each (command, working directory)."""
    runs = [{"run": run, **({"working-directory": directory} if directory else {})} for run, directory in steps]
    return {GITHUB_WORKFLOW: json.dumps({"jobs": {"test": {"runs-on": "ubuntu-latest", "steps": runs}}})}


def _package(name: str) -> dict[str, str]:
    return {
        f"packages/{name}/package.json": json.dumps({"name": name, "main": "index.js"}),
        f"packages/{name}/index.js": "",
    }


WORKSPACES = {
    "package.json": json.dumps({"private": True, "workspaces": ["packages/*"]}),
    **_package("a"),
    **_package("b"),
}
MIXED = {
    "CMakeLists.txt": "project(app CXX)\n",
    "src/main.cpp": "",
    "python/pyproject.toml": "[project]\nname = 'bindings'\n",
    "python/bindings/__init__.py": "",
}


def _units(files: dict[str, str]) -> list[tuple[str, tuple[str, ...], list[str]]]:
    with temp_project(files) as root:
        return [
            (unit.directory, unit.build_systems, sorted(unit.languages)) for unit in make_context(root).facts.of(Unit)
        ]


def _coverage(files: dict[str, str]) -> Result:
    with temp_project(files) as root:
        return coverage.run(make_context(root))


class UnitTests(unittest.TestCase):
    def test_a_project_built_from_its_root_is_one_unit(self) -> None:
        nested = {"CMakeLists.txt": "", "src/CMakeLists.txt": "", "src/main.cpp": "", "test/CMakeLists.txt": ""}
        self.assertEqual(_units(nested), [(".", ("CMake",), ["C++"])])

    def test_workspace_members_are_units_of_their_own(self) -> None:
        self.assertEqual(
            _units(WORKSPACES),
            [(".", ("npm",), []), ("packages/a", ("npm",), ["JavaScript"]), ("packages/b", ("npm",), ["JavaScript"])],
        )
        cargo = {
            "Cargo.toml": '[workspace]\nmembers = ["crates/*"]\n',
            **{f"crates/{name}/Cargo.toml": "[package]\n" for name in ("x", "y")},
            **{f"crates/{name}/src/lib.rs": "" for name in ("x", "y")},
        }
        self.assertEqual(
            _units(cargo),
            [(".", ("Cargo",), []), ("crates/x", ("Cargo",), ["Rust"]), ("crates/y", ("Cargo",), ["Rust"])],
        )
        # A broken root declares no workspace; the named package below it is a package of its own all the same.
        broken = {"package.json": "{", **_package("a")}
        self.assertEqual([unit for unit, _, _ in _units(broken)], [".", "packages/a"])
        go = {"go.work": "go 1.23\n\nuse (\n\t./api\n\t./cli\n)\n", "api/go.mod": "", "api/a.go": "", "cli/go.mod": ""}
        self.assertEqual([unit for unit, _, _ in _units(go)], [".", "api", "cli"])

    def test_yarn_workspaces_under_packages_and_vendored_projects(self) -> None:
        yarn = {"package.json": json.dumps({"workspaces": {"packages": ["packages/*"]}}), **_package("a")}
        self.assertEqual([unit for unit, _, _ in _units(yarn)], [".", "packages/a"])
        vendored = {"CMakeLists.txt": "", "main.c": "", "deps/lib/package.json": "{}", "deps/lib/x.js": ""}
        self.assertEqual([unit for unit, _, _ in _units(vendored)], ["."])

    def test_pnpm_workspace_members_are_units_of_their_own(self) -> None:
        """pnpm declares its workspace in pnpm-workspace.yaml, not package.json (graphql-eslint, graphql-inspector:
        upstream #188): each member is a unit, named or not, with the role its directory tells."""
        unnamed = {"packages/c/package.json": json.dumps({"private": True, "main": "x.js"}), "packages/c/x.js": ""}
        files = {
            "package.json": json.dumps({"private": True}),
            "pnpm-workspace.yaml": "packages:\n  - packages/*\n  - examples/*\n  - '!packages/skipped'\n",
            **unnamed,
            "examples/b/package.json": json.dumps({"private": True}),
            "examples/b/index.js": "",
        }
        with temp_project(files) as root:
            units = make_context(root).facts.of(Unit)
        self.assertEqual(
            [(unit.directory, unit.role) for unit in units],
            [(".", "product"), ("examples/b", "example"), ("packages/c", "product")],
        )

    def test_a_mixed_language_project_has_a_unit_per_build_root(self) -> None:
        self.assertEqual(_units(MIXED), [(".", ("CMake",), ["C++"]), ("python", ("Python packaging",), ["Python"])])

    def test_a_nested_package_is_a_unit_with_the_role_its_directory_tells(self) -> None:
        """A package below another of its build system's is a project of its own (upstream #188): vapor's
        Benchmarks/Package.swift, phoenix's installer/ and integration_test/ Mix projects, dbt-utils' test project."""
        for files, expected in (
            (
                {"Package.swift": "", "Sources/a.swift": "", "Benchmarks/Package.swift": "", "Benchmarks/b.swift": ""},
                [(".", "product"), ("Benchmarks", "benchmark")],
            ),
            (
                {"mix.exs": "", "installer/mix.exs": "", "integration_test/mix.exs": ""},
                [(".", "product"), ("installer", "product"), ("integration_test", "test")],
            ),
            (
                {"dbt_project.yml": "name: utils\n", "integration_tests/dbt_project.yml": "name: utils_tests\n"},
                [(".", "product"), ("integration_tests", "test")],
            ),
        ):
            with self.subTest(files=files), temp_project(files) as root:
                units = make_context(root).facts.of(Unit)
                self.assertEqual([(unit.directory, unit.role) for unit in units], expected)

    def test_an_auxiliary_unit_without_tests_of_its_own_is_not_asked_for_them(self) -> None:
        """A cargo-fuzz crate or a benchmark package beside the product holds no tests, and need not (upstream #230);
        one that has tests is judged for them."""
        files = {
            "Cargo.toml": "[package]\nname = 'app'\n",
            "src/lib.rs": "#[test]\nfn t() {}\n",
            "fuzz/Cargo.toml": "[package]\nname = 'app-fuzz'\n",
            "fuzz/fuzz_targets/a.rs": "",
            **_workflow(("cargo test", None)),
        }
        result = _check("tests-run", files)
        self.assertEqual((result.status, [place.unit for place in result.places]), (Status.PASS, ["."]), result)
        files["fuzz/src/lib.rs"] = "#[test]\nfn t() {}\n"
        self.assertEqual([place.unit for place in _check("tests-run", files).places], [".", "fuzz"])

    def test_a_template_or_benchmark_unit_is_not_asked_for_the_products_gates(self) -> None:
        """fluentd's templates/new_gem is the gem `fluentd plugin-generator` writes, and puma's benchmark apps lock no
        dependencies (upstream #188): neither is asked for tests or a lock file beside the product."""
        files = {
            "Gemfile": "source 'https://rubygems.org'\ngem 'rake'\n",
            "Gemfile.lock": "GEM\n",
            "lib/app.rb": "",
            "spec/app_spec.rb": "describe 'app' do\nend\n",
            "templates/new_gem/Gemfile": "gem 'rspec'\n",
            "templates/new_gem/lib/x.rb": "",
            "benchmarks/sinatra/Gemfile": "gem 'sinatra'\n",
            "benchmarks/sinatra/app.rb": "",
            **_workflow(("bundle exec rspec", None)),
        }
        for name in ("tests-run", "dependency-management"):
            with self.subTest(name), temp_project(files) as root:
                result = checks_named(name)[0].run(make_context(root))
                self.assertEqual([place.unit for place in result.places], ["."], result)

    def test_a_templates_migrations_are_not_the_products(self) -> None:
        """koyo's blueprints are the projects `raco koyo new` writes, migrations included (upstream #188): the
        template's migrations are not asked to be checked beside the product's."""
        files = {
            "package.json": json.dumps({"name": "app"}),
            "migrations/0001-init.sql": "create table a (id int);\n",
            "blueprints/standard/package.json": json.dumps({"name": "app-name-here"}),
            "blueprints/standard/migrations/0001-users.sql": "create table users (id int);\n",
        }
        with temp_project(files) as root:
            result = checks_named("migration-safety")[0].run(make_context(root))
            self.assertEqual([place.unit for place in result.places], ["."], result)

    def test_a_nested_build_file_that_is_no_project_of_its_own_is_its_parents(self) -> None:
        """A CMake subdirectory, a package.json that only marks its directory's modules (`{"type": "module"}`), and a
        test fixture's manifest belong to the unit above them."""
        for files in (
            {"CMakeLists.txt": "", "lib/CMakeLists.txt": "", "lib/a.cpp": ""},
            {"package.json": json.dumps({"name": "app"}), "dist/package.json": json.dumps({"type": "module"})},
            {"pyproject.toml": "[project]\nname = 'app'\n", "tests/fixtures/x/pyproject.toml": "[project]\n"},
        ):
            with self.subTest(files=files):
                self.assertEqual([unit for unit, _, _ in _units(files)], ["."])


class MonorepoCoverageTests(unittest.TestCase):
    def test_each_unit_needs_coverage_and_findings_name_the_unit(self) -> None:
        result = _coverage({**WORKSPACES, **_workflow(("npx c8 node --test", "packages/a"))})
        self.assertEqual(result.status, Status.FAIL)
        self.assertEqual(
            result.message,
            "packages/a: branch coverage is reported with c8; "
            "packages/b: no branch coverage measurement found in what CI runs",
        )

    def test_a_run_outside_the_project_covers_none_of_it(self) -> None:
        result = _coverage({**MIXED, **_workflow(("cd /tmp/other && gcovr --xml x", None))})
        self.assertIn("C++: no branch coverage measurement found in what CI runs", result.message)

    def test_a_run_from_the_root_covers_every_unit(self) -> None:
        result = _coverage({**WORKSPACES, **_workflow(("npx c8 node --test", None))})
        self.assertEqual(
            result,
            Result.passed(
                "branch coverage is reported with c8",
                "consider failing CI when branch coverage falls below a threshold",
            ),
        )

    def test_each_language_of_a_mixed_project_is_judged_where_it_is(self) -> None:
        both = _workflow(("gcovr --xml cov.xml", None), ("coverage run --branch -m pytest", "python"))
        result = _coverage({**MIXED, **both})
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("Python: branch coverage is measured with coverage.py", result.message)
        only_cpp = _coverage({**MIXED, **_workflow(("gcovr --xml cov.xml", None))})
        self.assertIn("Python: no branch coverage measurement found in what CI runs", only_cpp.message)


def _scripts(files: dict[str, str]) -> list[tuple[tuple[str, ...], str | None]]:
    """The scripts of the workspace packages (each runs `vitest <package>`) that CI runs, and where they run."""
    with temp_project(files) as root:
        commands = make_context(root).facts.of(Command)
    return [(command.argv, command.directory) for command in commands if command.argv[0] == "vitest"]


MEMBERS = {
    **{f"packages/{name}/package.json": json.dumps({"scripts": {"test": f"vitest {name}"}}) for name in ("a", "b")},
    "packages/c/package.json": "{}",
}
CALLED_WORKFLOW = """on: workflow_call
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: gcovr --xml x
"""


class WorkspaceScriptTests(unittest.TestCase):
    def test_a_script_run_across_the_workspace_runs_each_packages_script(self) -> None:
        npm = {"package.json": json.dumps({"workspaces": ["packages/*"]}), **MEMBERS}
        pnpm = {
            "package.json": "{}",
            "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n  - '!packages/c'\n",
            **MEMBERS,
        }
        expected = [(("vitest", "a"), "packages/a"), (("vitest", "b"), "packages/b")]
        for files, line in (
            (npm, "npm run test --workspaces"),
            (npm, "npm test -ws"),
            (pnpm, "pnpm -r test"),
            (pnpm, "pnpm --filter ./packages/* run test"),
            (pnpm, "npx turbo run test"),
            (pnpm, "turbo test --filter=a"),
            (npm, "lerna run test"),
            (npm, "nx run-many -t test,lint"),
        ):
            with self.subTest(line=line):
                self.assertEqual(_scripts({**files, **_workflow((line, None))}), expected)
        self.assertEqual(_scripts({**npm, **_workflow(("nx graph", None), ("lerna version", None))}), [])
        broken = {"package.json": "{}", "pnpm-workspace.yaml": "packages: [", **MEMBERS}
        self.assertEqual(_scripts({**broken, **_workflow(("pnpm -r test", None))}), [])


class ReusableWorkflowTests(unittest.TestCase):
    def _facts(self, uses: str) -> tuple[list[str], list[str]]:
        caller = {
            GITHUB_WORKFLOW: json.dumps({"jobs": {"ci": {"uses": uses}}}),
            ".github/workflows/_build.yml": CALLED_WORKFLOW,
        }
        with temp_project(caller) as root:
            facts = make_context(root).facts
        return [job.id for job in facts.of(CiJob)], [unknown.subject for unknown in facts.of(Unknown)]

    def test_a_reusable_workflow_of_the_same_repository_is_read(self) -> None:
        for uses in ("./.github/workflows/_build.yml", "$/.github/workflows/_build.yml"):
            with self.subTest(uses=uses):
                jobs, unknowns = self._facts(uses)
                self.assertEqual(jobs, [f"{GITHUB_WORKFLOW}:ci → .github/workflows/_build.yml:build"])
                self.assertEqual(unknowns, [])

    def test_one_in_another_repository_or_missing_is_unknown(self) -> None:
        for uses in ("org/repo/.github/workflows/build.yml@v1", "./.github/workflows/missing.yml"):
            with self.subTest(uses=uses):
                self.assertEqual(self._facts(uses), ([], ["job ci"]))


COMPOSITE_ACTION = """name: build
inputs:
  tasks:
    default: build
  flags:
    default: false
runs:
  using: composite
  steps:
    - run: ./gradlew ${{ inputs.tasks }} --scan=${{ inputs.flags }}
      shell: bash
      continue-on-error: true
    - uses: $/.github/actions/nested
      with:
        targets: [lint, "${{ inputs.tasks }}"]
    - not a step
"""


class LocalActionTests(unittest.TestCase):
    def _facts(self, step: dict[str, object], files: dict[str, str]) -> tuple[list[tuple[str, ...]], list[str]]:
        workflow = {GITHUB_WORKFLOW: json.dumps({"jobs": {"ci": {"runs-on": "ubuntu-latest", "steps": [step]}}})}
        with temp_project({**workflow, **files}) as root:
            facts = make_context(root).facts
        return [command.argv for command in facts.of(Command)], [unknown.subject for unknown in facts.of(Unknown)]

    def test_a_local_composite_actions_steps_run_in_the_job_with_its_inputs(self) -> None:
        files = {
            ".github/actions/build/action.yml": COMPOSITE_ACTION,
            ".github/actions/nested/action.yaml": "runs:\n  using: composite\n  steps:\n    - run: echo lint\n",
        }
        commands, unknowns = self._facts({"uses": "./.github/actions/build", "with": {"tasks": "check"}}, files)
        self.assertEqual(commands, [("./gradlew", "check", "--scan=false"), ("echo", "lint")])
        self.assertEqual(unknowns, [])
        with temp_project(
            {
                **files,
                GITHUB_WORKFLOW: json.dumps(
                    {"jobs": {"ci": {"runs-on": "x", "steps": [{"uses": "./.github/actions/build"}]}}}
                ),
            }
        ) as root:
            [first, *_] = make_context(root).facts.of(Command)
        self.assertEqual(first.argv, ("./gradlew", "build", "--scan=false"))
        self.assertEqual([str(origin) for origin in first.via], [f"{GITHUB_WORKFLOW}:1:44 (jobs.ci.steps[0])"])
        self.assertEqual(str(first.origin), ".github/actions/build/action.yml:10:7 (runs.steps[0].run)")

    def test_javascript_and_docker_actions_run_their_own_code(self) -> None:
        node = {".github/actions/js/action.yml": "runs:\n  using: node20\n  main: index.js\n"}
        self.assertEqual(self._facts({"uses": "./.github/actions/js"}, node), ([], []))

    def test_a_missing_local_action_is_unknown(self) -> None:
        self.assertEqual(
            self._facts({"uses": "./.github/actions/gone"}, {}), ([], ["the action ./.github/actions/gone"])
        )

    def test_an_action_that_uses_itself_ends(self) -> None:
        looping = {
            ".github/actions/loop/action.yml": "runs:\n  using: composite\n  steps:\n"
            "    - uses: ./.github/actions/loop\n    - run: echo once\n"
        }
        commands, _ = self._facts({"uses": "./.github/actions/loop"}, looping)
        self.assertEqual(set(commands), {("echo", "once")})


HELPER_SCRIPTS = {
    "CMakeLists.txt": "project(app CXX)\n",
    "src/main.cpp": "",
    "scripts/release.py": "import sys\n",
    **_workflow(("cmake --build build", None)),
}
ADVISORY = "a warning, not a failure: the Python here is auxiliary code (--auxiliary tooling)"
PRACTICES = ("static-analysis", "code-formatting", "coverage", "tests-run", "type-checking", "compiler-warnings")


def _check(name: str, files: dict[str, str], auxiliary: tuple[str, ...] = ()) -> Result:
    with temp_project(files) as root:
        return checks_named(name)[0].run(make_context(root, auxiliary=auxiliary))


def _place(result: Result, ecosystem: str) -> Placed:
    """The result's place for `ecosystem`, which it must have one of."""
    [found] = (place for place in result.places if place.ecosystem == ecosystem)
    return found


def _ecosystems(result: Result) -> set[str]:
    return {place.ecosystem for place in result.places}


class AuxiliaryCodeTests(unittest.TestCase):
    """A language is the product's and held to every practice, in whatever directory it is, until `--auxiliary`
    names code (by role, language or directory) that is not, or unless it is written only in auxiliary code (tests,
    examples, docs, tooling, benchmarks: upstream #182): that code is still judged in full, but a failure is a
    warning, and the report says what named the code."""

    def test_a_language_only_in_helper_scripts_is_auxiliary_by_default(self) -> None:
        """A C++ project's release script in Python is tooling: Python is not a language of the product."""
        advisory = "a warning, not a failure: the Python here is auxiliary code (only in tooling code)"
        for name in (*PRACTICES, "platform-matrix"):
            with self.subTest(name):
                result = _check(name, HELPER_SCRIPTS)
                python = _place(result, "Python")
                self.assertEqual((python.result.status, python.auxiliary), (Status.WARN, ("only in tooling code",)))
                self.assertIn(advisory, python.result.details)
                self.assertIn("Python (auxiliary: only in tooling code): ", result.message)

    def test_a_language_with_product_code_is_judged_as_the_products_in_its_helper_scripts_too(self) -> None:
        for name in (*PRACTICES, "platform-matrix"):
            with self.subTest(name):
                result = _check(name, {**HELPER_SCRIPTS, "src/gen.py": ""})
                python = _place(result, "Python")
                self.assertEqual((python.result.status, python.auxiliary), (Status.FAIL, ()))
                self.assertNotIn("auxiliary", result.message + "".join(result.details))

    def test_every_practice_warns_about_code_named_auxiliary_by_its_role(self) -> None:
        for name in (*PRACTICES, "platform-matrix"):
            with self.subTest(name):
                result = _check(name, HELPER_SCRIPTS, ("tooling",))
                python = _place(result, "Python")
                self.assertEqual((python.result.status, python.auxiliary), (Status.WARN, ("tooling",)))
                self.assertIn(ADVISORY, python.result.details)
                self.assertIn("Python (auxiliary: tooling): ", result.message)
                self.assertIn(f"Python (auxiliary: tooling): {ADVISORY}", result.details)

    def test_code_is_named_by_its_language_or_ecosystem_or_a_directory_as_given(self) -> None:
        for named, ecosystem in (("Python", "Python"), ("scripts/", "Python"), ("c++", "C++")):
            with self.subTest(named):
                result = _check("static-analysis", HELPER_SCRIPTS, (named,))
                place = _place(result, ecosystem)
                self.assertEqual((place.result.status, place.auxiliary), (Status.WARN, (named,)))
                self.assertIn(f"{ecosystem} (auxiliary: {named}): ", result.message)
                self.assertIn(f"(--auxiliary {named})", "".join(result.details))

    def test_a_finding_about_auxiliary_code_alone_is_labelled_too(self) -> None:
        result = _check("type-checking", HELPER_SCRIPTS, ("tooling",))  # C++ is skipped: no known type checker
        self.assertEqual(result.status, Status.WARN)
        self.assertTrue(result.message.startswith("Python (auxiliary: tooling): no type checker runs"), result.message)
        self.assertIn(f"Python (auxiliary: tooling): {ADVISORY}", result.details)

    def test_the_label_and_the_detail_name_everything_that_named_the_code(self) -> None:
        result = _check("static-analysis", {**HELPER_SCRIPTS, "docs/conf.py": ""}, ("tooling", "docs"))
        self.assertIn("; Python (auxiliary: docs, tooling): ", result.message)
        self.assertIn("(--auxiliary docs --auxiliary tooling)", result.details[-1])

    def test_a_run_in_the_scripts_directory_or_from_the_root_counts(self) -> None:
        for directory, auxiliary in (("scripts", ()), (None, ()), ("scripts", ("tooling",)), (None, ("tooling",))):
            with self.subTest((directory, auxiliary)):
                steps = (
                    ("cmake --build build", None),
                    ("ruff check .", directory),
                    ("coverage run --branch -m pytest", directory),
                )
                files = {**HELPER_SCRIPTS, **_workflow(*steps)}
                for name in ("static-analysis", "coverage"):
                    python = _place(_check(name, files, auxiliary), "Python")
                    self.assertEqual(python.result.status, Status.PASS, python.result.message)

    def test_a_run_only_in_auxiliary_code_does_not_speak_for_the_product(self) -> None:
        files = {"pyproject.toml": "[project]\nname = 'app'\n", "src/app.py": "", "scripts/release.py": ""}
        files |= _workflow(("ruff check .", "scripts"))
        self.assertEqual(_place(_check("static-analysis", files), "Python").result.status, Status.PASS)
        named = _place(_check("static-analysis", files, ("tooling",)), "Python")
        self.assertEqual((named.result.status, named.auxiliary), (Status.FAIL, ()))

    def test_vendored_code_is_not_judged(self) -> None:
        files = {**HELPER_SCRIPTS, "third_party/tool/helper.py": ""}
        del files["scripts/release.py"]
        for auxiliary in ((), ("third_party/",)):
            self.assertNotIn("Python", _ecosystems(_check("static-analysis", files, auxiliary)))

    def test_a_project_of_only_scripts_is_all_product_until_named(self) -> None:
        scripts = {"scripts/release.py": "", **_workflow(("echo build", None))}
        result = _check("static-analysis", scripts)
        self.assertEqual((result.status, _place(result, "Python").auxiliary), (Status.FAIL, ()))
        named = _check("static-analysis", scripts, ("scripts/",))
        self.assertEqual((named.status, _place(named, "Python").auxiliary), (Status.WARN, ("scripts/",)))

    def test_test_helpers_can_be_named_without_losing_the_tests(self) -> None:
        files = {**HELPER_SCRIPTS, "tests/check.py": ""}
        files["CMakeLists.txt"] = "project(app CXX)\nenable_testing()\nadd_test(NAME t COMMAND t)\n"
        files |= _workflow(("ctest --test-dir build", None))
        del files["scripts/release.py"]
        python = _place(_check("static-analysis", files), "Python")
        self.assertEqual((python.result.status, python.auxiliary), (Status.WARN, ("only in test code",)))
        named = _check("tests-run", files, ("test",))
        self.assertEqual(_place(named, "C++").result.status, Status.PASS, named.message)
        python = _place(named, "Python")
        self.assertEqual((python.result.status, python.auxiliary), (Status.WARN, ("test",)))

    def test_test_fixtures_configure_nothing_of_the_product(self) -> None:
        """A test fixture's manifest or tool configuration is not the product's (upstream #188: PHP_CodeSniffer's
        tests/**/Fixtures/phpcs.xml.dist, composer's fixture composer.json files)."""
        files = {
            "composer.json": json.dumps({"require": {"php": ">=8.1"}}),
            "composer.lock": "{}",
            "src/A.php": "<?php\n",
            "phpcs.xml.dist": "<ruleset/>\n",
            "tests/Fixtures/a/composer.json": json.dumps({"require": {"x/y": "1"}}),
            "tests/Fixtures/a/phpcs.xml.dist": "<ruleset/>\n",
            **_workflow(("vendor/bin/phpcs", None)),
        }
        dependencies = _check("dependency-management", files)
        self.assertNotIn("Fixtures", dependencies.message)
        formatting = _check("code-formatting", files)
        self.assertIn("phpcs.xml.dist is defined", formatting.message)
        self.assertNotIn("Fixtures", formatting.message)

    def test_an_examples_configuration_configures_nothing_of_the_product(self) -> None:
        """A tool configuration an example directory shows its readers is not the product's (upstream #188:
        Perl-Critic's examples/perlcriticrc), though the example is no project of its own."""
        files = {
            "composer.json": json.dumps({"require": {"php": ">=8.1"}}),
            "src/A.php": "<?php\n",
            "phpcs.xml.dist": "<ruleset/>\n",
            "examples/phpcs.xml.dist": "<ruleset/>\n",
            **_workflow(("vendor/bin/phpcs", None)),
        }
        formatting = _check("code-formatting", files)
        self.assertIn("phpcs.xml.dist is defined", formatting.message)
        self.assertNotIn("examples/", formatting.message)

    def test_an_examples_tests_are_still_tests(self) -> None:
        """What an example holds is set apart as configuration, not as tests: Awesome-CV's tests are the example
        documents CI builds (examples/cv.tex)."""
        files = {
            "awesome-cv.cls": "\\ProvidesClass{awesome-cv}\n",
            "examples/cv.tex": "\\documentclass{awesome-cv}\n\\begin{document}\n\\end{document}\n",
            **_workflow(("latexmk -pdf -cd examples/cv.tex", None)),
        }
        result = _check("tests-run", files)
        self.assertEqual(result.status, Status.PASS, result.message)

    def test_what_is_named_must_be_a_role_a_language_or_a_directory(self) -> None:
        with temp_project(HELPER_SCRIPTS) as root:
            for named in ("scripts", "vendored", "product", "/"):
                with self.subTest(named):
                    code, _, errors = run_cli("--auxiliary", named, str(root))
                    self.assertEqual(code, EXIT_USAGE)
                    self.assertIn(f"--auxiliary {named}: ", errors)
                    self.assertIn("a directory (with a /)", errors)

    def test_the_json_report_and_the_grid_mark_auxiliary_code(self) -> None:
        with temp_project(HELPER_SCRIPTS) as root:
            code, output, _ = run_cli("--only", "static-analysis", "--format", "json", str(root))
            self.assertEqual(code, EXIT_FAILURE)
            [report] = json.loads(output)
            self.assertEqual(report["status"], "FAIL")
            places = {(place["ecosystem"], place["unit"]): place for place in report["places"]}
            self.assertEqual(set(places), {("C++", "."), ("CMake", "."), ("Python", ".")})
            python = places[("Python", ".")]
            self.assertEqual(
                (python["status"], python["auxiliary"], python["tools"]), ("WARN", ["only in tooling code"], [])
            )
            self.assertEqual(python["message"], "no static analyzer runs")
            arguments = ("--only", "static-analysis", "--auxiliary", "tooling", str(root))
            code, output, _ = run_cli(*arguments, "--format", "json")
            self.assertEqual(code, EXIT_FAILURE)
            [report] = json.loads(output)
            [python] = [place for place in report["places"] if place["ecosystem"] == "Python"]
            self.assertEqual((python["status"], python["auxiliary"]), ("WARN", ["tooling"]))
            self.assertIn(f"Python (auxiliary: tooling): {ADVISORY}", report["details"])
            code, grid, _ = run_cli(*arguments, "--format", "markdown")
            self.assertIn(f"| {MARKS[Status.WARN]} (auxiliary) |", grid)
            code, facts, _ = run_cli(*arguments, "--facts")
            self.assertIn(
                {"kind": "AuxiliaryCode", "origin": ".", "named": ["tooling"], "implied": ["Python"]}, json.loads(facts)
            )

    def test_the_answers_say_what_named_the_code(self) -> None:
        with temp_project({**HELPER_SCRIPTS, "benchmarks/run.py": ""}) as root:
            answers = static_analysis("Python", make_context(root, auxiliary=("tooling", "benchmark")).facts)
        self.assertEqual(answers.auxiliary, {".": ("benchmark", "tooling")})
        self.assertEqual(answers.as_dict()["auxiliary"], {".": ["benchmark", "tooling"]})
        self.assertEqual(
            [(answer.unit, answer.auxiliary) for answer in answers.units], [(".", ("benchmark", "tooling"))]
        )


class SelectorTests(unittest.TestCase):
    """What `--auxiliary` names, and which code it matches."""

    def test_an_ecosystem_names_every_language_of_it_whatever_the_case(self) -> None:
        named = Selectors.parse(("jvm", "PYTHON"))
        self.assertEqual(named.matching("src/A.java", "Java"), "jvm")
        self.assertEqual(named.matching("src/B.kt", "Kotlin"), "jvm")
        self.assertEqual(named.matching("src/a.c", "C"), "")
        self.assertEqual(named.matching("a.py", "Python"), "PYTHON")
        self.assertEqual(named.matching("a.rs", "Rust"), "")

    def test_a_role_is_matched_by_the_directories_a_path_is_in(self) -> None:
        named = Selectors.parse(("Tooling", "test"))
        self.assertEqual(named.matching("scripts/x.py", "Python"), "Tooling")
        self.assertEqual(named.matching("tools", None, directory=True), "Tooling")
        self.assertEqual(named.matching("tests/helpers/x.py", None), "test")
        self.assertEqual(named.matching("src/x.py", "Python"), "")

    def test_a_directory_matches_what_is_at_or_below_it(self) -> None:
        named = Selectors.parse(("ci/", "tools/legacy"))
        self.assertEqual(named.matching("ci/build.sh", None), "ci/")
        self.assertEqual(named.matching("ci", None, directory=True), "ci/")
        self.assertEqual(named.matching("tools/legacy/old.py", "Python"), "tools/legacy")
        self.assertEqual(named.matching("tools/new.py", "Python"), "")
        self.assertEqual(Selectors.parse(()).matching("scripts/x.py", "Python"), "")

    def test_a_name_that_is_nothing_known_is_refused(self) -> None:
        for named in ("scripts", "vendored", "product", "/", "Shellfish"):
            with self.subTest(named), self.assertRaises(ValueError) as refused:
                Selectors.parse((named,))
            self.assertIn(f"--auxiliary {named}: ", str(refused.exception))
