"""Kinds of Swift project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="SwiftPM",
        files={"Package.swift": "// swift-tools-version:6.0\n", "Sources/App/main.swift": ""},
        languages=frozenset({"Swift"}),
        build_systems=frozenset({"SwiftPM"}),
    ),
    ProjectLayout(
        name="Xcode Swift",
        files={"App.xcodeproj/project.pbxproj": "", "App/AppDelegate.swift": ""},
        languages=frozenset({"Swift"}),
        build_systems=frozenset({"Xcode"}),
    ),
)
