"""The JavaScript/TypeScript profile's rules, judged by the generic checks in every JavaScript project layout."""

import json
import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.committed_artifacts import committed_artifacts
from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.checks.coverage import coverage
from project_validator.checks.dependency_audit import dependency_audit
from project_validator.checks.dependency_management import dependency_management
from project_validator.checks.function_limits import function_limits
from project_validator.checks.license import license_
from project_validator.checks.platform_matrix import platform_matrix
from project_validator.checks.security_scanning import security_scanning
from project_validator.checks.static_analysis import static_analysis
from project_validator.checks.tests_run import tests_run
from project_validator.checks.type_checking import type_checking
from project_validator.checks.vcs_ignore import vcs_ignore
from project_validator.checks.warnings_as_errors import warnings_as_errors
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.javascript import DEPENDENCIES, JAVASCRIPT_AND_TYPESCRIPT, NODE_MODULES, TYPE_CHECKING
from project_validator.facts import Command, Unknown
from tests.support import (
    GITHUB_WORKFLOW,
    github_job,
    make_context,
    run_as,
    run_in_layout,
    temp_project,
)

STRICT_TSCONFIG = {"tsconfig.json": '{\n  // checked strictly\n  "compilerOptions": {"strict": true,},\n}\n'}


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


def _package(**fields: object) -> dict[str, str]:
    return {"package.json": json.dumps(fields)}


def _scripts(**scripts: str) -> dict[str, str]:
    return _package(main="index.js", scripts=scripts)


class RecognitionTests(unittest.TestCase):
    def _languages(self, files: dict[str, str]) -> frozenset[str]:
        with temp_project(files) as root:
            return make_context(root).structure.languages

    # package.json is the tooling of projects in many languages.
    def test_a_package_json_alone_is_not_a_javascript_project(self) -> None:
        self.assertEqual(self._languages({"package.json": '{"devDependencies": {"jscpd": "4"}}'}), frozenset())
        self.assertEqual(self._languages({"package.json": "not json"}), frozenset())

    def test_a_package_with_entry_points_or_sources_is(self) -> None:
        for files in (_package(bin={"app": "cli.js"}), {"package.json": "{}", "src/app.mjs": ""}):
            with self.subTest(files=files):
                self.assertEqual(self._languages(files), frozenset({"JavaScript"}))
        self.assertEqual(self._languages({"deno.jsonc": "{}"}), frozenset({"TypeScript"}))
        self.assertEqual(self._languages({"app.tsx": ""}), frozenset({"TypeScript"}))

    def test_sources_in_node_modules_do_not_count(self) -> None:
        self.assertEqual(self._languages({"node_modules/left-pad/index.js": ""}), frozenset())


class JavaScriptTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, JAVASCRIPT_AND_TYPESCRIPT)

    def test_formatting_is_enforced_by_any_formatter_in_ci_or_a_script_it_runs(self) -> None:
        for files in (
            _ci("npx prettier --check ."),
            _ci("biome ci"),
            _ci("deno fmt --check"),
            _ci("dprint check"),
            _ci("pnpm exec oxfmt --check"),
            {**_scripts(fmt="oxfmt"), **_ci("pnpm fmt", "git diff --exit-code")},
            {**_scripts(fmt="prettier -c src"), **_ci("pnpm fmt")},
            {**_scripts(check="npm run fmt", fmt="prettier -l ."), **_ci("yarn run check")},
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(code_formatting, files).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, _ci("npx prettier --write .")).status, Status.FAIL)
        # A script CI never runs enforces nothing.
        self.assertEqual(self._run(code_formatting, _scripts(fmt="prettier --check .")).status, Status.FAIL)

    def test_a_formatter_configuration_without_ci_warns(self) -> None:
        for files in ({".prettierrc.json": "{}"}, _package(main="index.js", prettier={})):
            with self.subTest(files=files):
                self.assertEqual(self._run(code_formatting, files).status, Status.WARN)

    def test_scripts_run_their_pre_and_post_scripts_and_deno_tasks(self) -> None:
        pre = {**_scripts(pretest="prettier --check .", test="node --test"), **_ci("npm t")}
        self.assertEqual(self._run(code_formatting, pre).status, Status.PASS)
        deno = {"deno.json": '{"tasks": {"fmt": "deno fmt --check"}}', **_ci("deno task fmt")}
        self.assertEqual(self._run(code_formatting, deno).status, Status.PASS)
        loop = {**_scripts(a="npm run b", b="npm run a"), **_ci("npm run a")}
        self.assertEqual(self._run(code_formatting, loop).status, Status.FAIL)

    def test_tests_are_test_and_spec_files(self) -> None:
        for path in ("src/app.test.ts", "app.spec.jsx", "lib/app_test.mjs", "src/__tests__/app.js"):
            with self.subTest(path=path):
                result = self._run(tests_run, {path: "", **_ci("npx vitest run")})
                self.assertEqual(result, Result.passed("JavaScript or TypeScript tests found in 1 file(s)"))
        for path in ("src/latest.js", "test.md", "app.test.py"):
            with self.subTest(path=path):
                self.assertEqual(self._run(tests_run, {path: ""}).status, Status.FAIL)

    def test_ci_must_run_the_tests(self) -> None:
        self.assertEqual(self._run(tests_run, {"a.test.js": ""}).status, Status.WARN)
        for command in ("npm test", "pnpm test", "node --experimental-strip-types --test", "bun test", "jest"):
            with self.subTest(command=command):
                self.assertEqual(self._run(tests_run, {"a.test.js": "", **_ci(command)}).status, Status.PASS)

    def test_coverage_is_found_in_what_ci_runs_and_the_runner_settings_it_reads(self) -> None:
        jest = {"jest.config.js": "export default { collectCoverage: true };\n"}
        vitest = {"vitest.config.ts": "test: { coverage: { provider: 'v8', enabled: true } }\n"}
        cases = (
            ("c8", _ci("npx --yes c8 node --test")),
            ("nyc", _scripts(test="nyc mocha") | _ci("npm test")),
            ("Jest", jest | _ci("pnpm exec jest")),
            ("Jest", _package(main="index.js", jest={"collectCoverage": True}) | _ci("npx jest")),
            ("Vitest", vitest | _scripts(test="vitest run") | _ci("npm test")),
            ("deno test", _ci("deno test --coverage=cov")),
            ("node --test", _ci("node --test --experimental-test-coverage")),
        )
        for tool, files in cases:
            with self.subTest(tool=tool):
                self.assertEqual(self._run(coverage, files), Result.passed(f"branch coverage is reported with {tool}"))
        # A runner's settings count only where CI runs it; Bun counts lines.
        for files in (
            jest,
            vitest | _ci("npx jest"),
            _ci("npx vitest run", "git checkout c8a1b2"),
            _ci("bun test --coverage"),
        ):
            with self.subTest(files=files):
                self.assertEqual(self._run(coverage, files).status, Status.FAIL)

    def test_one_linter_is_enough(self) -> None:
        for command, linter in (("npx eslint .", "eslint"), ("biome ci", "biome lint"), ("deno lint", "deno lint")):
            with self.subTest(command=command):
                result = self._run(compiler_warnings, _ci(command))
                self.assertEqual(result, Result.passed(f"strict JavaScript linters are enabled: {linter}"))
        result = self._run(compiler_warnings, _ci("npm ci"))
        self.assertEqual(result, Result.failed("no JavaScript linters found; enable at least eslint"))

    def test_a_lint_warning_must_fail_ci(self) -> None:
        for command in ("eslint --max-warnings=0 .", "biome lint --error-on-warnings", "biome ci", "deno lint"):
            with self.subTest(command=command):
                self.assertEqual(self._run(warnings_as_errors, _ci(command)).status, Status.PASS)
        for command in ("eslint .", "eslint --max-warnings 10 .", "biome lint"):
            with self.subTest(command=command):
                self.assertEqual(self._run(warnings_as_errors, _ci(command)).status, Status.FAIL)

    def test_package_manager_audits_count_but_not_signature_checks(self) -> None:
        for command in ("npm audit --omit=dev", "pnpm audit", "yarn npm audit", "bun audit", "osv-scanner ."):
            with self.subTest(command=command):
                self.assertEqual(self._run(dependency_audit, _ci(command)).status, Status.PASS)
        self.assertEqual(self._run(dependency_audit, _ci("npm audit signatures")).status, Status.WARN)


class FunctionLimitTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, function_limits, files, JAVASCRIPT_AND_TYPESCRIPT)

    def test_eslint_max_lines_per_function_limits_functions_when_eslint_runs(self) -> None:
        config = {"eslint.config.js": 'export default [{ rules: { "max-lines-per-function": ["error", 40] } }];\n'}
        expected = Result.passed("function length is limited with eslint max-lines-per-function (eslint.config.js)")
        self.assertEqual(self._run({**config, **_ci("npx eslint .")}), expected)
        warned = Result.warned("max-lines-per-function is enabled in eslint.config.js but CI does not run eslint")
        self.assertEqual(self._run(config), warned)

    def test_a_disabled_rule_limits_nothing(self) -> None:
        for setting in ('"off"', "0", '["off"]'):
            with self.subTest(setting=setting):
                config = {".eslintrc.json": f'{{"rules": {{"max-lines-per-function": {setting}}}}}'}
                result = self._run({**config, **_ci("eslint .")})
                self.assertEqual(result.status, Status.FAIL)
                self.assertIn("max-lines-per-function", result.message)


class StaticAnalysisTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, JAVASCRIPT_AND_TYPESCRIPT)

    def test_a_linter_is_the_static_analyzer(self) -> None:
        files = {"eslint.config.js": "export default [];\n", **_scripts(lint="eslint ."), **_ci("npm run lint")}
        self.assertEqual(self._run(static_analysis, files), Result.passed("eslint (eslint.config.js) runs"))
        warned = run_in_layout(self, "npm JavaScript", static_analysis, {"biome.json": "{}"})
        self.assertEqual(warned.message, "biome lint is configured (biome.json) but does not run")

    def test_security_lints_are_a_plugin_or_semgrep_rules(self) -> None:
        for files in (
            {"eslint.config.mjs": 'import security from "eslint-plugin-security";\n'},
            _ci("semgrep scan --config p/typescript"),
        ):
            with self.subTest(files=files):
                self.assertEqual(run_in_layout(self, "npm JavaScript", security_scanning, files).status, Status.PASS)
        self.assertEqual(
            run_in_layout(self, "npm JavaScript", security_scanning, _ci("semgrep scan --config p/python")).status,
            Status.WARN,
        )


class TypeCheckingTests(unittest.TestCase):
    def _npm(self, files: dict[str, str]) -> Result:
        return run_in_layout(self, "npm JavaScript", type_checking, files)

    def _deno(self, files: dict[str, str]) -> Result:
        return run_in_layout(self, "Deno TypeScript", type_checking, files)

    def test_tsc_type_checks_and_strict_mode_is_the_bonus(self) -> None:
        typecheck = {**_scripts(typecheck="tsc --noEmit"), **_ci("pnpm typecheck")}
        expected = 'tsc (tsconfig.json) runs; strict mode bonus: "strict": true in tsconfig.json'
        self.assertEqual(self._npm({**STRICT_TSCONFIG, **typecheck}), Result.passed(expected))

    def test_the_strictest_base_configuration_is_strict(self) -> None:
        for extends in ('"@tsconfig/strictest/tsconfig.json"', '["@tsconfig/node22", "@tsconfig/strictest"]'):
            with self.subTest(extends=extends):
                files = {"jsconfig.json": f'{{"extends": {extends}}}', **_ci("npx tsc -p jsconfig.json")}
                self.assertIn("@tsconfig/strictest in jsconfig.json", self._npm(files).message)

    def test_without_strict_mode_it_is_suggested(self) -> None:
        files = {"tsconfig.json": '{"extends": "./base.json"}', **_ci("npx vue-tsc --noEmit")}
        self.assertEqual(self._npm(files), Result.passed("tsc (tsconfig.json) runs", TYPE_CHECKING.strict_hint))
        self.assertEqual(self._npm(_ci("npm ci")), Result.failed("no type checker runs", TYPE_CHECKING.hint))

    def test_deno_checks_strictly_unless_told_not_to(self) -> None:
        strict = "deno check (deno.json) runs; strict mode bonus: Deno's default strict mode (deno.json)"
        self.assertEqual(self._deno(_ci("deno test")), Result.passed(strict))
        lax = {"deno.json": '{"compilerOptions": {"strict": false}}', **_ci("deno check main.ts")}
        self.assertEqual(self._deno(lax).details, (TYPE_CHECKING.strict_hint,))


class DependencyTests(unittest.TestCase):
    def _npm(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, "npm JavaScript", selected, files)

    def test_declared_dependencies_must_be_locked_even_in_a_library(self) -> None:
        declared = _package(main="index.js", peerDependencies={"react": "^19"})
        expected = Result.warned("dependencies are declared in package.json but not locked", DEPENDENCIES.lock_hint)
        self.assertEqual(self._npm(dependency_management, declared), expected)
        locked = self._npm(dependency_management, {**declared, "pnpm-lock.yaml": "lockfileVersion: '9.0'\n"})
        self.assertEqual(
            locked, Result.passed("dependencies are declared in package.json and locked in pnpm-lock.yaml")
        )

    def test_deno_imports_are_dependencies(self) -> None:
        files = {"deno.jsonc": '{"imports": {"@std/assert": "jsr:@std/assert@1"}}', "deno.lock": "{}"}
        expected = Result.passed("dependencies are declared in deno.jsonc and locked in deno.lock")
        self.assertEqual(run_in_layout(self, "Deno TypeScript", dependency_management, files), expected)

    def test_without_dependencies_there_is_nothing_to_lock(self) -> None:
        self.assertEqual(self._npm(dependency_management, {}), Result.passed("no dependencies are declared"))
        # A package.json that does not parse declares nothing.
        broken = {"package.json": '{"main": "index.js", "dependencies": {', "index.js": ""}
        self.assertEqual(self._npm(dependency_management, broken), Result.passed("no dependencies are declared"))

    def test_the_package_license_must_match_the_license_file(self) -> None:
        mit = "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        files = {"LICENSE": mit, **_package(main="index.js", license="Apache-2.0")}
        result = self._npm(license_, files)
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("package.json declares Apache-2.0", result.details[0])
        self.assertEqual(self._npm(license_, {**files, **_package(license="MIT", main="a.js")}).status, Status.PASS)


class OutputTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_as(self, selected, files, JAVASCRIPT_AND_TYPESCRIPT)

    def test_node_modules_must_be_ignored(self) -> None:
        for entry in ("node_modules", "/node_modules/", "**/node_modules"):
            with self.subTest(entry=entry):
                self.assertEqual(self._run(vcs_ignore, {".gitignore": f"{entry}\n"}).status, Status.PASS)
        self.assertEqual(self._run(vcs_ignore, {".gitignore": "dist/\n"}).status, Status.WARN)

    def test_dependencies_coverage_and_build_info_are_outputs_but_dist_is_not(self) -> None:
        result = self._run(committed_artifacts, {"coverage/lcov.info": "", "tsconfig.tsbuildinfo": ""})
        self.assertEqual(result.message, "2 build outputs are committed")
        self.assertEqual(self._run(committed_artifacts, {"dist/index.js": ""}).status, Status.PASS)
        # Only git, not a walk of the files, sees a committed node_modules.
        self.assertEqual(NODE_MODULES.artifact("packages/a/node_modules/x/index.js"), "packages/a/node_modules/")

    def test_the_platform_matrix_counts_node_deno_and_bun_versions(self) -> None:
        files = {
            GITHUB_WORKFLOW: """\
                jobs:
                  node:
                    runs-on: ${{ matrix.os }}
                    strategy:
                      matrix:
                        os: [ubuntu-latest, windows-latest]
                        node: ["22", lts/*]
                    steps:
                      - uses: actions/setup-node@v5
                        with:
                          node-version: ${{ matrix.node }}
                  deno:
                    runs-on: macos-latest
                    container: denoland/deno:alpine-2.5.0
                    steps:
                      - run: deno test
                """
        }
        result = self._run(platform_matrix, files)
        self.assertIn("3 runtime version(s) (2.5.0, 22, lts/*)", result.message)


DENO_TASKS = '{\n  // tasks\n  "tasks": {"fmt": "deno fmt --check", "check": {"command": "deno check main.ts"}}\n}\n'
PACKAGES = {
    "package.json": json.dumps(
        {"scripts": {"pretest": "tsc --noEmit", "test": "vitest run", "posttest": "c8 report", "lint": "eslint ."}}
    ),
    "web/package.json": json.dumps({"scripts": {"build": "vite build"}}),
    "deno.jsonc": DENO_TASKS,
}


class ScriptExpansionTests(unittest.TestCase):
    """The package.json scripts and deno.json tasks a CI command runs are commands of the job too."""

    def _expanded(self, *steps: str) -> list[tuple[str, ...]]:
        with temp_project({**PACKAGES, **github_job("ubuntu-latest", *steps)}) as root:
            facts = make_context(root).facts
        return [command.argv for command in facts.of(Command) if command.via]

    def test_npm_runs_a_script_between_its_pre_and_post_scripts(self) -> None:
        expected = [("tsc", "--noEmit"), ("vitest", "run"), ("c8", "report")]
        for step in ("npm test", "npm t", "npm run test", "yarn test"):
            with self.subTest(step=step):
                self.assertEqual(self._expanded(step), expected)

    def test_pnpm_and_bun_run_only_the_script(self) -> None:
        for step in ("pnpm test", "pnpm run test", "bun run test"):
            with self.subTest(step=step):
                self.assertEqual(self._expanded(step), [("vitest", "run")])

    def test_a_package_manager_pointed_at_a_directory_reads_its_package(self) -> None:
        self.assertEqual(self._expanded("npm --prefix web run build", "pnpm -C web build"), [("vite", "build")] * 2)

    def test_deno_tasks(self) -> None:
        self.assertEqual(
            self._expanded("deno task fmt", "deno task check"),
            [("deno", "fmt", "--check"), ("deno", "check", "main.ts")],
        )

    def test_package_manager_commands_are_not_scripts(self) -> None:
        commands = (
            "npm --version",
            "npm ci",
            "npm run",
            "pnpm install",
            "yarn add left-pad",
            "bun test",
            "pnpm vitest",
        )
        self.assertEqual(self._expanded(*commands), [])

    def test_a_script_that_does_not_exist_is_unknown(self) -> None:
        with temp_project({**PACKAGES, **github_job("ubuntu-latest", "npm run build", "deno task nope")}) as root:
            unknown = make_context(root).facts.of(Unknown)
        self.assertEqual(
            [(fact.subject, fact.reason) for fact in unknown],
            [("the script build", "package.json has none"), ("the task nope", "no deno.json defines it")],
        )
