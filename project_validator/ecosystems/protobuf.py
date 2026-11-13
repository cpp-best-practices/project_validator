"""Protobuf: `.proto` schemas (and the gRPC services they define), a format judged by buf, or protoc: the schemas
compile (`schema-validation`: `buf build`, `protoc`), lint (`static-analysis`: `buf lint`, with the rules `buf.yaml`
sets) and are formatted (`code-formatting`: `buf format --diff --exit-code`). `bufbuild/buf-action` builds, lints,
formats and checks breaking changes unless told otherwise. Breaking changes (`buf breaking`) are the schema
compatibility practice of #85, not yet built; `buf.lock` beside a `buf.yaml` with `deps` is a dependency rule
(#24)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.schema import validated, validator
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import defined_by, starts, when

PROTOBUF = "Protobuf"
PROTOBUF_ONLY = frozenset({PROTOBUF})

PROTOBUF_ECOSYSTEM = Ecosystem(
    label="Protobuf",
    kind="format",
    languages=PROTOBUF_ONLY,
    source_suffixes={".proto": PROTOBUF},
    ci_programs=(("buf",), ("protoc",), ("grpc_tools.protoc",)),
    ci_usage=re.compile(r"(?<![\w-])buf-(?:setup-)?action\b"),
)

BUF_SETTINGS = file_reader("buf", ("buf.yaml", "buf.yml", "buf.work.yaml"))

# `buf build` compiles every module; protoc compiles the files it is given.
BUF_BUILD = validator(
    name="buf build",
    languages=PROTOBUF_ONLY,
    how="buf build (or bufbuild/buf-action)",
    validates=when(starts(("buf", "build")), validated),
)
PROTOC = validator(
    name="protoc",
    languages=PROTOBUF_ONLY,
    how="protoc --proto_path=proto proto/**/*.proto",
    validates=when(starts(("protoc",), ("grpc_tools.protoc",)), validated),
)
# buf lint has the STANDARD rules by default; buf.yaml's `lint` section sets the project's.
BUF_LINT = analyzer(
    name="buf lint",
    languages=PROTOBUF_ONLY,
    how="buf lint",
    analyses=when(starts(("buf", "lint")), analysed),
    rules=defined_by(files=(BUF_SETTINGS.name,)),
)
# `buf format --diff` prints what it would change; only `--exit-code` fails on it. `-w` rewrites the files.
BUF_FORMAT = format_tool(
    name="buf format",
    languages=PROTOBUF_ONLY,
    can={Enforcement.CHECK: "buf format --diff --exit-code", Enforcement.APPLY: "buf format -w"},
    formats=flagged(("buf", "format"), checks=("--exit-code",), applies=("-w", "--write")),
    style=defined_by(),
)


def _buf_action(inputs: Mapping[str, str]) -> tuple[tuple[str, ...], ...]:
    """`bufbuild/buf-action` builds, and lints, formats and checks breaking changes unless an input says `false`."""
    commands: list[tuple[str, ...]] = [("buf", "build")]
    for step, command in (
        ("lint", ("buf", "lint")),
        ("format", ("buf", "format", "--diff", "--exit-code")),
        ("breaking", ("buf", "breaking")),
    ):
        if inputs.get(step, "true").strip().lower() != "false":
            commands.append(command)
    return tuple(commands)


BUF_ACTION = Action(name="bufbuild/buf-action", runs=_buf_action)
