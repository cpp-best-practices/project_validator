"""CI providers that are detected by their configuration files and scanned heuristically."""

from project_validator.ci import CiProvider
from project_validator.text import pattern

AZURE_PIPELINES = CiProvider(
    name="Azure Pipelines",
    files=("azure-pipelines.yml", ".azure-pipelines.yml"),
    badges=(
        pattern("Azure Pipelines", r"dev\.azure\.com/\S+/_apis/build/status|img\.shields\.io/azure-devops/build/"),
    ),
)
APPVEYOR = CiProvider(
    name="AppVeyor",
    files=("appveyor.yml", ".appveyor.yml"),
    badges=(pattern("AppVeyor", r"ci\.appveyor\.com/api/projects/status|img\.shields\.io/appveyor/"),),
)
CIRCLECI = CiProvider(
    name="CircleCI",
    files=(".circleci/config.yml",),
    linters=(pattern("circleci config validate", r"\bcircleci\s+config\s+validate\b"),),
    lint_hint="CircleCI: run circleci config validate in CI",
    badges=(
        pattern(
            "CircleCI", r"circleci\.com/(?:gh|bb)/\S+\.svg|dl\.circleci\.com/status-badge/|img\.shields\.io/circleci/"
        ),
    ),
)
TRAVIS_CI = CiProvider(
    name="Travis CI",
    files=(".travis.yml",),
    badges=(pattern("Travis CI", r"travis-ci\.(?:org|com)/\S+\.svg|img\.shields\.io/travis/"),),
)
JENKINS = CiProvider(
    name="Jenkins",
    files=("Jenkinsfile",),
    badges=(pattern("Jenkins", r"/buildStatus/icon\b|/badge/icon\b|img\.shields\.io/jenkins/build"),),
)
BUILDKITE = CiProvider(
    name="Buildkite",
    files=(".buildkite/pipeline.yml", "buildkite.yml"),
    badges=(pattern("Buildkite", r"badge\.buildkite\.com/"),),
)
DRONE = CiProvider(
    name="Drone",
    files=(".drone.yml",),
    badges=(pattern("Drone", r"/api/badges/[^/\s]+/[^/\s]+/status\.svg|img\.shields\.io/drone/build/"),),
)
CIRRUS_CI = CiProvider(
    name="Cirrus CI",
    files=(".cirrus.yml",),
    badges=(pattern("Cirrus CI", r"api\.cirrus-ci\.com/github/\S+\.svg|img\.shields\.io/cirrus/"),),
)
BITBUCKET_PIPELINES = CiProvider(name="Bitbucket Pipelines", files=("bitbucket-pipelines.yml",))
WOODPECKER = CiProvider(
    name="Woodpecker",
    files=(".woodpecker.yml",),
    directories=(".woodpecker",),
    badges=(pattern("Woodpecker", r"/api/badges/\d+/status\.svg"),),
)
