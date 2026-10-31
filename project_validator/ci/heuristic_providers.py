"""CI providers that are detected by their configuration files and scanned heuristically."""

from project_validator.ci import CiProvider

AZURE_PIPELINES = CiProvider(name="Azure Pipelines", files=("azure-pipelines.yml", ".azure-pipelines.yml"))
APPVEYOR = CiProvider(name="AppVeyor", files=("appveyor.yml", ".appveyor.yml"))
CIRCLECI = CiProvider(name="CircleCI", files=(".circleci/config.yml",))
TRAVIS_CI = CiProvider(name="Travis CI", files=(".travis.yml",))
JENKINS = CiProvider(name="Jenkins", files=("Jenkinsfile",))
BUILDKITE = CiProvider(name="Buildkite", files=(".buildkite/pipeline.yml", "buildkite.yml"))
DRONE = CiProvider(name="Drone", files=(".drone.yml",))
CIRRUS_CI = CiProvider(name="Cirrus CI", files=(".cirrus.yml",))
BITBUCKET_PIPELINES = CiProvider(name="Bitbucket Pipelines", files=("bitbucket-pipelines.yml",))
WOODPECKER = CiProvider(name="Woodpecker", files=(".woodpecker.yml",), directories=(".woodpecker",))
