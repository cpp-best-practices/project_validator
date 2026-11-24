"""The foundations questions stand on: structure and setting facts, and the queries over the fact database."""

from __future__ import annotations

import unittest

from project_validator.facts import ConfigurationFile, Facts, Origin, Setting, Unknown
from project_validator.facts.roles import role
from project_validator.facts.settings import (
    file_reader,
    ini_settings,
    json_settings,
    key_value_settings,
    known_settings_readers,
    settings_facts,
    toml_settings,
    yaml_settings,
)
from project_validator.facts.structure import SourceFile
from project_validator.questions import known_questions
from tests.support import github_job, make_context, temp_project


def _setting(path: str, key: str, value: object, tool: str = "tool") -> Setting:
    return Setting(origin=Origin(path=path), tool=tool, key=key, value=value)


def _settings(path: str, files: dict[str, str]) -> list[tuple[str, str, object]]:
    """(tool, key, value) of every setting the built-in readers find in `path` of a project of `files`."""
    with temp_project(files) as root:
        found = make_context(root).facts.of(Setting)
    return [(setting.tool, setting.key, setting.value) for setting in found if setting.path == path]


class QueryTests(unittest.TestCase):
    FACTS = Facts(
        (
            _setting("a/setup.cfg", "run.branch", "true"),
            _setting("pyproject.toml", "run.branch", "false"),
            _setting("pyproject.toml", "run.source", ("app",)),
            _setting("pyproject.toml", "x", 1, tool="other"),
            ConfigurationFile(origin=Origin(path="phpunit.xml.dist"), reader="PHPUnit"),
        )
    )

    def test_where_filters_by_field(self) -> None:
        self.assertEqual(len(self.FACTS.where(Setting, tool="tool")), 3)
        self.assertEqual(
            [found.path for found in self.FACTS.where(Setting, key="run.branch", value="true")], ["a/setup.cfg"]
        )

    def test_settings_in_the_order_of_the_files_given(self) -> None:
        found = self.FACTS.settings("tool", paths=["pyproject.toml", "a/setup.cfg"])
        self.assertEqual([setting.value for setting in found], ["false", ("app",), "true"])
        self.assertEqual(self.FACTS.setting("tool", "run.branch", paths=["a/setup.cfg"]).value, "true")  # type: ignore[union-attr]
        self.assertIsNone(self.FACTS.setting("tool", "run.omit"))

    def test_which_file_a_tool_reads(self) -> None:
        self.assertEqual(self.FACTS.configured("tool", ["setup.cfg", "pyproject.toml"]), "pyproject.toml")
        self.assertEqual(self.FACTS.first_file("PHPUnit", ["phpunit.xml", "phpunit.xml.dist"]), "phpunit.xml.dist")
        self.assertIsNone(self.FACTS.first_file("PHPUnit", ["phpunit.xml"]))

    def test_facts_extend(self) -> None:
        unread = Unknown(origin=Origin(path="x"), subject="s", reason="r")
        more = self.FACTS + iter([unread])
        self.assertEqual((len(more.all), len(more.of(Unknown)), len(self.FACTS.of(Unknown))), (6, 1, 0))


class FormatTests(unittest.TestCase):
    def test_a_yaml_setting_is_placed_where_the_file_has_it(self) -> None:
        text = "verifier:\n  name: ansible\n  options:\n    v: true\nother: 1\n"
        found = [str(fact.origin) for fact in yaml_settings("molecule", "molecule.yml", text, "verifier")]
        self.assertEqual(found, ["molecule.yml:2:3 (name)", "molecule.yml:4:5 (options.v)"])

    def test_tables_and_sections_are_flattened_under_dotted_keys(self) -> None:
        toml = list(toml_settings("t", "p.toml", '[tool.x.run]\nbranch = true\nomit = ["a"]\n', "tool", "x"))
        self.assertEqual([(found.key, found.value) for found in toml], [("run.branch", True), ("run.omit", ("a",))])  # type: ignore[attr-defined]
        self.assertEqual(toml[0].origin, Origin(path="p.toml", at=("run", "branch")))
        ini = list(
            ini_settings(
                "t", "s.cfg", "[x:run]\nbranch = 1\n[other]\na = 1\n", lambda s: "run." if s == "x:run" else None
            )
        )
        self.assertEqual([(found.key, found.value) for found in ini], [("run.branch", "1")])  # type: ignore[attr-defined]
        json = list(json_settings("t", "c.json", '{"a": {"b": 1}} // x', "a", comments=True))
        self.assertEqual([(found.key, found.value) for found in json], [("b", 1)])  # type: ignore[attr-defined]
        pairs = list(key_value_settings("t", "gcovr.cfg", "# xml = no\nxml = out.xml\nflag\n"))
        self.assertEqual([(found.key, found.value) for found in pairs], [("xml", "out.xml")])

    def test_a_file_that_does_not_parse_is_unknown_for_its_tool(self) -> None:
        for found in (
            toml_settings("t", "p.toml", "[x", "tool"),
            ini_settings("t", "s.cfg", "[x", lambda _: ""),
            json_settings("t", "c.json", "{"),
        ):
            [unknown] = list(found)
            self.assertIsInstance(unknown, Unknown)
            self.assertEqual(unknown.tools, ("t",))  # type: ignore[attr-defined]

    def test_a_test_fixture_that_does_not_parse_hides_nothing(self) -> None:
        """vite's playground/resolve/utf8-bom-package/package.json is a resolver fixture whose point is its BOM: not
        the project's Jest settings, so nothing is unknown for it (#184). The project's own still is."""
        broken = '﻿{"name": "bom"}\n'
        for path, unknown in (("playground/resolve/utf8-bom-package/package.json", False), ("package.json", True)):
            with self.subTest(path=path), temp_project({path: broken, "index.js": ""}) as root:
                found = make_context(root).facts.of(Unknown)
                unknowns = [fact.origin.path for fact in found if fact.origin.path == path]
                self.assertEqual(bool(unknowns), unknown, unknowns)


POM = "<project xmlns='http://maven.apache.org/POM/4.0.0'><build><plugins><plugin>"
POM += "<artifactId>jacoco-maven-plugin</artifactId><executions><execution><goals><goal>report</goal>"
POM += "</goals></execution></executions></plugin></plugins></build></project>"
# (path, text, the settings read from it)
READ = (
    ("pom.xml", POM, [("Maven", "plugin.jacoco-maven-plugin", ("report",))]),
    (
        "pom.xml",
        "<plugin><artifactId>a</artifactId><goal>b</goal></plugin><x>",
        [("Maven", "plugin.a", ("b",))],
    ),
    (
        "build.gradle",
        "plugins { id 'jacoco' }\ntest { finalizedBy jacocoTestReport }\n",
        [("Gradle", "plugin", "jacoco"), ("Gradle", "task", "jacocoTestReport")],
    ),
    (
        "App.csproj",
        "<Project><PropertyGroup><Nullable>enable</Nullable></PropertyGroup></Project>",
        [("MSBuild", "Nullable", "enable"), ("MSBuild warning settings", "Nullable enable", True)],
    ),
    (
        "App.csproj",
        "<Nullable>enable</Nullable><Other>x</Other>",
        [
            ("MSBuild", "Nullable", "enable"),
            ("MSBuild", "Other", "x"),
            ("MSBuild warning settings", "Nullable enable", True),
        ],
    ),
    (
        "ci.runsettings",
        '<DataCollector friendlyName="XPlat code coverage"><',
        [("VSTest", "DataCollector", "XPlat code coverage")],
    ),
    (
        "App.xctestplan",
        '{"defaultOptions": {"codeCoverage": false}}',
        [("Xcode", "defaultOptions.codeCoverage", False)],
    ),
    ("jest.config.json", '{"collectCoverage": true}', [("Jest", "collectCoverage", True)]),
)


class ReaderTests(unittest.TestCase):
    def test_readers_are_found_not_listed(self) -> None:
        names = {reader.name for reader in known_settings_readers()}
        self.assertLessEqual({"coverage.py", "pytest", "gcovr", "CMake", "MSBuild", "Maven", "Gradle"}, names)

    def test_a_configuration_file_a_command_names_is_read(self) -> None:
        files = {"ci/cov.ini": "[run]\nbranch = on\n", **github_job("x", "coverage run --rcfile=ci/cov.ini -m x")}
        self.assertEqual(_settings("ci/cov.ini", files), [("coverage.py", "run.branch", "on")])
        self.assertEqual(_settings("ci/cov.ini", {"ci/cov.ini": "[run]\nbranch = on\n"}), [])

    def test_a_reader_reads_files_by_name_by_glob_or_by_the_end_of_their_path(self) -> None:
        readers = (
            file_reader("ruff", ("ruff.toml",)),
            file_reader("cmake", ("*.cmake",)),
            file_reader("sorbet", ("sorbet/config",)),
            file_reader("ruff too", ("ruff.toml", "*.toml")),  # a reader that matches a file twice reads it once
        )
        paths = ("ruff.toml", "lib/ruff.toml", "cmake/Deps.cmake", "sorbet/config", "svc/sorbet/config", "svc/config")
        with temp_project(dict.fromkeys((*paths, "other.toml", "third_party/x/ruff.toml"), "")) as root:
            found = settings_facts(make_context(root), readers, Facts())
            read = [(fact.reader, fact.path) for fact in found if isinstance(fact, ConfigurationFile)]
        expected = [("cmake", "cmake/Deps.cmake"), ("ruff", "lib/ruff.toml"), ("ruff too", "lib/ruff.toml")]
        expected += [("ruff too", "other.toml"), ("ruff", "ruff.toml"), ("ruff too", "ruff.toml")]
        self.assertEqual(read, [*expected, ("sorbet", "sorbet/config"), ("sorbet", "svc/sorbet/config")])

    def test_a_vendored_projects_configuration_is_not_read_unless_a_command_names_it(self) -> None:
        vendored = {"deps/lib/.coveragerc": "[run]\nbranch = on\n"}
        self.assertEqual(_settings("deps/lib/.coveragerc", vendored), [])
        named = {**vendored, **github_job("x", "coverage run --rcfile=deps/lib/.coveragerc -m x")}
        self.assertEqual(_settings("deps/lib/.coveragerc", named), [("coverage.py", "run.branch", "on")])

    def test_build_and_test_settings(self) -> None:
        for path, text, expected in READ:
            with self.subTest(path=path, text=text):
                # Readers are found module by module, so their order is not part of what is read.
                self.assertCountEqual(_settings(path, {path: text}), expected)

    def test_a_scheme_that_does_not_parse_is_unknown(self) -> None:
        with temp_project({"A.xcscheme": "<Scheme>"}) as root:
            [unknown] = make_context(root).facts.of(Unknown)
        self.assertEqual((unknown.subject, unknown.tools), ("the Xcode settings", ("Xcode",)))


ROLES = (
    ("web/coi-serviceworker.min.js", "vendored"),
    ("lib/jquery-min.js", "vendored"),
    ("third_party/json/json.hpp", "vendored"),
    ("deps/jemalloc/src/arena.c", "vendored"),
    ("tests/test_app.py", "test"),
    ("platform-tooling-support-tests/projects/vintage/src/A.java", "test"),
    ("examples/minimal/server.ts", "example"),
    ("docs/mkdocs/scripts/build.py", "docs"),
    ("tools/gen.py", "tooling"),
    ("benches/parse.rs", "benchmark"),
    ("src/minimal.js", "product"),
    ("src/main.cpp", "product"),
    ("src/main/java/com/example/App.java", "product"),
    # Below a source root, only a test directory tells (upstream #184).
    ("src/test/java/com/example/AppTest.java", "test"),
    ("src/main/java/com/example/tools/Gen.java", "product"),
    ("src/vendor/x.php", "vendored"),
    ("tokio/fuzz/fuzz_targets/a.rs", "test"),
    ("stress-test/src/main.rs", "test"),
    ("tests-integration/src/lib.rs", "test"),
    # Perl's test directories: t/ (mojo's template fixtures), and xt/ for author tests (upstream #184).
    ("t/mojolicious/json_config_lite_app.json", "test"),
    ("xt/author/pod.t", "test"),
    # vite's end-to-end test projects; json-fortran's parser test inputs (#184, #235).
    ("playground/glob-import/root/dir/node_modules/x/index.js", "test"),
    ("files/inputs/invalid.json", "test"),
)


class StructureTests(unittest.TestCase):
    def test_the_role_of_code_is_told_by_the_directories_it_is_in(self) -> None:
        for path, expected in ROLES:
            with self.subTest(path=path):
                self.assertEqual(role(path), expected)
        directories = (role("examples", directory=True), role("."), role(".", directory=True))
        self.assertEqual(directories, ("example", "product", "product"))
        # A unit is told by its own name first, below a source root too.
        self.assertEqual(role("internal/tools", directory=True), "tooling")
        self.assertEqual(role("internal/tools/gen.go"), "product")

    def test_a_directory_named_for_what_it_holds_tells_its_role(self) -> None:
        """Names the corpus uses besides the plain ones (upstream #182, #188): Kubernetes' `hack/` and Dart's `tool/`
        maintainer scripts, phoenix's and Flutter's `integration_test/`, dart-lang/http's `flutter_http_example/`,
        clap's `clap_bench/` and ruff's `ruff_benchmark/`, rust-lang/book's `listings/`, fpm's `example_packages/`
        and koyo's `blueprints/` (project templates)."""
        for path, expected in (
            ("charts/a/hack/sync.py", "tooling"),
            ("tool/update_readme.dart", "tooling"),
            ("integration_test/docker.sh", "test"),
            ("pkgs/flutter_http_example/lib/main.dart", "example"),
            ("example_packages/c_includes/fpm.toml", "example"),
            ("listings/ch01/hello/src/main.rs", "example"),
            ("clap_bench/benches/a.rs", "benchmark"),
            ("crates/ruff_benchmark/src/lib.rs", "benchmark"),
            ("koyo-lib/blueprints/standard/package.json", "template"),
            # bamarni/composer-bin-plugin's tool installs (guzzle).
            ("vendor-bin/phpstan/composer.json", "tooling"),
        ):
            with self.subTest(path=path):
                self.assertEqual(role(path), expected)
        # A library for testing is the product (bloc's bloc_test package).
        self.assertEqual(role("packages/bloc_test", directory=True), "product")

    def test_vendored_code_is_recorded_but_adds_no_language(self) -> None:
        with temp_project({"main.c": "", "web/sw.min.js": ""}) as root:
            context = make_context(root)
            sources = {(source.path, source.role) for source in context.facts.of(SourceFile)}
            self.assertEqual(sources, {("main.c", "product"), ("web/sw.min.js", "vendored")})
            self.assertEqual(context.structure.languages, frozenset({"C"}))
            self.assertEqual(context.structure.as_dict()["vendored"], ["web/sw.min.js"])


class QuestionTests(unittest.TestCase):
    def test_questions_are_found_not_listed(self) -> None:
        self.assertIn("coverage", {question.name for question in known_questions()})


class PreCommitHookTests(unittest.TestCase):
    def test_each_hook_is_recorded_and_an_unparsed_configuration_is_unknown(self) -> None:
        hooks = (
            "repos:\n  - repo: local\n    hooks:\n      - id: lint\n        entry: lizard\n        args: [-L, '30']\n"
        )
        self.assertEqual(
            _settings(".pre-commit-config.yaml", {".pre-commit-config.yaml": hooks}),
            [("pre-commit", "hook", "local lint lizard -L 30")],
        )
        with temp_project({".pre-commit-config.yaml": "repos: [\n"}) as root:
            [unknown] = make_context(root).facts.of(Unknown)
        self.assertEqual(unknown.subject, "the pre-commit hooks")
