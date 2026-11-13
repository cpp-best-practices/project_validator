"""Kinds of Protobuf project, for tests that run a check in every layout: a buf module."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

PROTO = """\
syntax = "proto3";

package shop.v1;

// A price list and its total.
service ShopService {
  rpc Total(TotalRequest) returns (TotalResponse);
}

message TotalRequest {
  repeated int32 prices = 1;
}

message TotalResponse {
  int32 total = 1;
}
"""
BUF = "version: v2\nmodules:\n  - path: proto\nlint:\n  use:\n    - STANDARD\nbreaking:\n  use:\n    - FILE\n"

LAYOUTS = (
    ProjectLayout(
        name="Protobuf module",
        files={"buf.yaml": BUF, "proto/shop/v1/shop.proto": PROTO},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"Protobuf", "YAML"}),
    ),
)
