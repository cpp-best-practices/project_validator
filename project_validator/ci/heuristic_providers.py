"""CI providers that are detected by their configuration files and scanned heuristically."""

from __future__ import annotations

from project_validator.ci import CiProvider
from project_validator.text import pattern

JENKINS = CiProvider(
    name="Jenkins",
    files=("Jenkinsfile",),
    badges=(pattern("Jenkins", r"/buildStatus/icon\b|/job/\S+/badge/icon\b|img\.shields\.io/jenkins/build"),),
    configured_elsewhere=True,
)
BUILDKITE = CiProvider(
    name="Buildkite",
    files=(".buildkite/pipeline.yml", "buildkite.yml"),
    badges=(pattern("Buildkite", r"badge\.buildkite\.com/"),),
    configured_elsewhere=True,
)
DRONE = CiProvider(
    name="Drone",
    files=(".drone.yml",),
    badges=(pattern("Drone", r"/api/badges/[^/\s]+/[^/\s]+/status\.svg|img\.shields\.io/drone/build/"),),
)
BITBUCKET_PIPELINES = CiProvider(name="Bitbucket Pipelines", files=("bitbucket-pipelines.yml",))
WOODPECKER = CiProvider(
    name="Woodpecker",
    files=(".woodpecker.yml",),
    directories=(".woodpecker",),
    badges=(pattern("Woodpecker", r"/api/badges/\d+/status\.svg"),),
)
# OCaml-CI builds and tests every opam package of a GitHub repository that installs its app, with no configuration.
OCAML_CI = CiProvider(
    name="OCaml-CI",
    badges=(pattern("OCaml-CI", r"ocaml\.ci\.dev/badge/|ci\.ocamllabs\.io/badge/"),),
    configured_elsewhere=True,
)
