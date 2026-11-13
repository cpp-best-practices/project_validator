"""Kinds of API description, for tests that run a check in every layout: an OpenAPI description."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

OPENAPI = """\
openapi: 3.1.0
info:
  title: Shop
  version: 1.0.0
paths:
  /total:
    post:
      operationId: total
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: array
              items:
                type: integer
      responses:
        "200":
          description: The sum of the prices.
          content:
            application/json:
              schema:
                type: integer
"""
ASYNCAPI = (
    "asyncapi: 3.0.0\ninfo:\n  title: Shop events\n  version: 1.0.0\nchannels:\n  priced:\n    address: shop/priced\n"
)

LAYOUTS = (
    ProjectLayout(
        name="OpenAPI description",
        files={"openapi.yaml": OPENAPI},
        languages=frozenset(),
        build_systems=frozenset(),
        formats=frozenset({"OpenAPI", "YAML"}),
    ),
)
