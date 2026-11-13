"""Protobuf: `.proto` schemas (and the gRPC services they define), a format judged by buf, or protoc: the schemas
compile (`schema-validation`: `buf build`, `protoc`), lint (`static-analysis`: `buf lint`, with the rules `buf.yaml`
sets) and are formatted (`code-formatting`: `buf format --diff --exit-code`). `bufbuild/buf-action` builds, lints,
formats and checks breaking changes unless told otherwise. Each file declares its `syntax` (or `edition`) and its
`package` (`schema-declared`), and CI checks them for breaking changes (`schema-compatibility`: `buf breaking`, which
the action runs unless told otherwise). `buf.lock` beside a `buf.yaml` with `deps` is a dependency rule (#24)."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from project_validator.core import Project
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.analysis import analysed, analyzer
from project_validator.facts.declaration import Declaration, Declares, declaring
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, flagged, format_tool
from project_validator.facts.schema import compatibility_checked, compatibility_checker, validated, validator
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

# --- Declaration ----------------------------------------------------------------------------------------------------

_SYNTAX = re.compile(r'^\s*(syntax|edition)\s*=\s*"([^"]*)"\s*;', re.MULTILINE)
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


def proto_files(project: Project) -> Iterator[str]:
    return (path for path in project.files() if PurePosixPath(path).suffix == ".proto")


def _read_proto(text: str) -> Declaration:
    """What a `.proto` file declares: its `syntax` (`proto3`; or its `edition`), without which protoc reads it as
    proto2 with a warning, and its `package`, without which its messages are in the global namespace."""
    syntax, package = _SYNTAX.search(text), _PACKAGE.search(text)
    names = {
        syntax[1] if syntax else "syntax": syntax[2] if syntax else None,
        "package": package[1] if package else None,
    }
    return declaring(names)


PROTOBUF_DECLARES = Declares(
    format=PROTOBUF, what="syntax (or edition) and package", find=proto_files, read=_read_proto
)

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
# `buf breaking` compares the module with what it is told (`--against .git#branch=main`, or the registry).
BUF_BREAKING = compatibility_checker(
    name="buf breaking",
    languages=PROTOBUF_ONLY,
    how="buf breaking --against .git#branch=main (or bufbuild/buf-action)",
    checks=when(starts(("buf", "breaking")), compatibility_checked),
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
