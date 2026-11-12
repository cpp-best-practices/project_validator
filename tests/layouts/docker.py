"""Kinds of Docker project, for tests that run a check in every layout: a Dockerfile and nothing else."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Dockerfile",
        files={"Dockerfile": 'FROM alpine:3.20\nRUN apk add --no-cache curl\nUSER nobody\nCMD ["curl"]\n'},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"Dockerfile"}),
    ),
)
