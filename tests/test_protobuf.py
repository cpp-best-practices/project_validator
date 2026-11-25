"""The Protobuf profile: a format of .proto schemas, compiled, linted and formatted by buf or protoc."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
from project_validator.checks.schema_declared import schema_declared
from project_validator.checks.schema_validation import schema_validation
from project_validator.checks.static_analysis import static_analysis
from project_validator.core import Check, Result, Status
from project_validator.ecosystems.protobuf import PROTOBUF_ECOSYSTEM
from tests.layouts.protobuf import PROTO
from tests.support import github_action, github_job, make_context, run_in_layout, temp_project, uses

LAYOUT = "Protobuf module"
VALIDATED = "CI validates the documents against their schemas with {}"


def _ci(*steps: str) -> dict[str, str]:
    return github_job("ubuntu-latest", *steps)


class RecognitionTests(unittest.TestCase):
    def test_proto_files_are_the_format(self) -> None:
        with temp_project({"api/shop.proto": PROTO}) as root:
            structure = make_context(root).structure
        self.assertEqual((structure.languages, structure.formats), (frozenset(), frozenset({"Protobuf"})))
        self.assertEqual(structure.recognised_by["Protobuf"], (".proto files",))
        self.assertEqual((PROTOBUF_ECOSYSTEM.kind, PROTOBUF_ECOSYSTEM.toolchain), ("format", None))

    def test_ci_usage(self) -> None:
        for text in ("buf lint", "protoc -I proto proto/shop.proto", "uses: bufbuild/buf-action@v1"):
            with self.subTest(text=text):
                self.assertTrue(uses(PROTOBUF_ECOSYSTEM, text))
        self.assertFalse(uses(PROTOBUF_ECOSYSTEM, "go test ./..."))


class ProtobufTests(unittest.TestCase):
    def _run(self, selected: Check, files: dict[str, str]) -> Result:
        return run_in_layout(self, LAYOUT, selected, files)

    def test_the_schemas_compile_with_buf_or_protoc(self) -> None:
        for line, tool in (
            ("buf build", "buf build"),
            ("protoc --proto_path=proto proto/shop/v1/shop.proto", "protoc"),
            ("python -m grpc_tools.protoc -I proto --python_out=gen proto/shop/v1/shop.proto", "protoc"),
        ):
            with self.subTest(line=line):
                self.assertEqual(self._run(schema_validation, _ci(line)), Result.passed(VALIDATED.format(tool)))
        self.assertEqual(self._run(schema_validation, _ci("buf lint")).status, Status.FAIL)

    def test_bazel_compiles_the_schemas_its_proto_library_rules_name(self) -> None:
        """grpc-proto's only CI job is `bazelisk build //...` over BUILD files of proto_library rules, each of which
        protoc compiles (upstream #207)."""
        build = {"MODULE.bazel": "", "BUILD.bazel": 'proto_library(name = "shop_proto", srcs = ["api/shop.proto"])\n'}
        for line in ("bazelisk build //...", "bazel --batch test //api/..."):
            with self.subTest(line=line):
                result = self._run(schema_validation, {**build, **_ci(line)})
                self.assertEqual(result, Result.passed(VALIDATED.format("Bazel proto_library")))
        # Building without proto_library rules compiles no schema, nor does querying them.
        no_rules = {"MODULE.bazel": "", "BUILD.bazel": 'cc_library(name = "app")\n'}
        self.assertEqual(self._run(schema_validation, {**no_rules, **_ci("bazel build //...")}).status, Status.FAIL)
        self.assertEqual(self._run(schema_validation, {**build, **_ci("bazel query //...")}).status, Status.FAIL)

    def test_buf_lints_with_the_rules_buf_yaml_sets_and_formats_with_exit_code(self) -> None:
        self.assertEqual(self._run(static_analysis, _ci("buf lint")), Result.passed("buf lint (buf.yaml) runs"))
        # buf.yaml configures buf lint, so a CI that never runs it warns.
        self.assertEqual(self._run(static_analysis, _ci("buf build")).status, Status.WARN)
        for line in ("buf format --diff --exit-code", "buf format -d --exit-code proto"):
            with self.subTest(line=line):
                self.assertEqual(
                    self._run(code_formatting, _ci(line)), Result.passed("CI enforces the buf format style")
                )
        for line in ("buf format -d", "buf format -w"):
            with self.subTest(line=line):
                self.assertEqual(self._run(code_formatting, _ci(line)).status, Status.FAIL)

    def test_the_buf_action_builds_lints_and_formats_unless_told_otherwise(self) -> None:
        everything = github_action("bufbuild/buf-action@v1")
        self.assertEqual(self._run(schema_validation, everything).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, everything).status, Status.PASS)
        self.assertEqual(self._run(code_formatting, everything).status, Status.PASS)
        only_build = github_action("bufbuild/buf-action@v1", lint="false", format="false", breaking="false")
        self.assertEqual(self._run(schema_validation, only_build).status, Status.PASS)
        self.assertEqual(self._run(static_analysis, only_build).status, Status.WARN)
        self.assertEqual(self._run(code_formatting, only_build).status, Status.FAIL)


UNPACKAGED = 'syntax = "proto3";\n\nmessage A {}\n'


class PackageRuleTests(unittest.TestCase):
    """A `.proto` file's package is asked for as buf lint's `PACKAGE_DEFINED` rule: a module whose `buf.yaml` does not
    have the rule does not ask it of its files (bufbuild/protovalidate's examples)."""

    def _details(self, files: dict[str, str]) -> tuple[str, ...]:
        with temp_project(files) as root:
            return schema_declared.run(make_context(root)).details

    def test_a_module_that_excepts_the_rule_does_not_ask_for_a_package(self) -> None:
        for buf in (
            "version: v2\nlint:\n  use: [STANDARD]\n  except: [PACKAGE_DEFINED]\n",
            "version: v1\nlint:\n  use:\n    - FIELD_LOWER_SNAKE_CASE\n",
            "version: v2\nmodules:\n  - path: proto\n    lint:\n      except: [PACKAGE_DEFINED]\n",
        ):
            with self.subTest(buf=buf):
                details = self._details({"buf.yaml": buf, "proto/a.proto": UNPACKAGED})
                self.assertFalse([line for line in details if "no package" in line], details)

    def test_the_rule_is_asked_by_default_and_by_its_categories(self) -> None:
        for files in (
            {"proto/a.proto": UNPACKAGED},
            {"buf.yaml": "version: v2\nlint:\n  use: [MINIMAL]\n", "proto/a.proto": UNPACKAGED},
            # A configuration that cannot be read, or says nothing of the rule, leaves buf's default.
            {"buf.yaml": "lint: [\n", "proto/a.proto": UNPACKAGED},
            {"buf.yml": "- version\n", "proto/a.proto": UNPACKAGED},
            {
                "buf.yaml": "version: v2\nmodules:\n  - path: other\n    lint: {except: [PACKAGE_DEFINED]}\n",
                "proto/a.proto": UNPACKAGED,
            },
            # Another module's exception is not this one's.
            {
                "other/buf.yaml": "version: v2\nlint:\n  except: [PACKAGE_DEFINED]\n",
                "other/b.proto": UNPACKAGED,
                "proto/a.proto": UNPACKAGED,
            },
        ):
            with self.subTest(files=sorted(files)):
                self.assertIn("proto/a.proto: no package", self._details(files))
