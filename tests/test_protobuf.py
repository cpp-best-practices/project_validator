"""The Protobuf profile: a format of .proto schemas, compiled, linted and formatted by buf or protoc."""

from __future__ import annotations

import unittest

from project_validator.checks.code_formatting import code_formatting
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
