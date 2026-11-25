"""Bazel, read without running it: its BUILD files are parsed for the rules they call (`syntax`), and its commands
read for their build type and the tests they run (`build`), with the options their rc files give them (`rc`)."""

from __future__ import annotations

from project_validator.build_systems.bazel.build import BAZEL, BAZEL_BUILD_FILES, BAZEL_TEST
from project_validator.build_systems.bazel.rc import BAZELRC

__all__ = ["BAZEL", "BAZELRC", "BAZEL_BUILD_FILES", "BAZEL_TEST"]
