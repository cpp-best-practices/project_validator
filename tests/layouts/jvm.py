"""Kinds of JVM project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Maven Java",
        files={"pom.xml": "<project/>\n", "src/main/java/App.java": ""},
        languages=frozenset({"Java"}),
        build_systems=frozenset({"Maven"}),
    ),
    ProjectLayout(
        name="Gradle Kotlin",
        files={"settings.gradle.kts": "", "build.gradle.kts": "", "src/main/kotlin/App.kt": ""},
        languages=frozenset({"Kotlin"}),
        build_systems=frozenset({"Gradle"}),
    ),
)
