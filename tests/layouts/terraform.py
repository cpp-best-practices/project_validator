"""Kinds of Terraform project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Terraform configuration",
        files={"main.tf": 'terraform {\n  required_version = ">= 1.9"\n}\n'},
        languages=frozenset({"Terraform"}),
        build_systems=frozenset(),
    ),
)
