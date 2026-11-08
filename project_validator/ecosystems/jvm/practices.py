"""JVM's practices: the settings it asks for, and how they are worded (see
`project_validator.facts.practices`)."""

import re

from project_validator.ecosystems.jvm import GRADLE_BUILD_FILES, JAVA, JVM_LANGUAGES, KOTLIN, POM
from project_validator.facts.practices import Practice, PracticeName, Wording, always, required, requirement_reader
from project_validator.text import Pattern


def _setting(name: str, regex: str) -> Pattern:
    return Pattern(name, re.compile(regex, re.IGNORECASE | re.DOTALL))


XLINT = _setting("-Xlint:all", r"-Xlint(?::all)?(?![:\w-])")


# The Kotlin compiler warns by default; a Kotlin-only project is judged by warnings-as-errors.
KOTLIN_WARNINGS = _setting(
    "Kotlin's default warnings", r"\bkotlin-maven-plugin\b|\borg\.jetbrains\.kotlin\b|\bkotlin\s*\(\s*[\"']jvm[\"']"
)


_JVM_WARNINGS_AS_ERRORS = (
    required(_setting("-Werror", r"-Werror\b")),
    required(_setting("allWarningsAsErrors", r"\ballWarningsAsErrors\b(?:\s*(?:=|\.set\s*\()\s*|>\s*)true\b")),
)


JVM_WARNING_SETTINGS = requirement_reader(
    "JVM warning settings",
    (POM, *GRADLE_BUILD_FILES),
    (required(XLINT), required(KOTLIN_WARNINGS), *_JVM_WARNINGS_AS_ERRORS),
)


JAVA_WARNINGS = Practice(
    name=PracticeName.WARNINGS,
    languages=frozenset({JAVA}),
    requirements=always(required(XLINT)),
    reads=(JVM_WARNING_SETTINGS.name,),
    words=Wording(
        kind="JVM compiler warnings",
        hint="add -Xlint:all to javac's compilerArgs",
    ),
)


KOTLIN_WARNINGS_PRACTICE = Practice(
    name=PracticeName.WARNINGS,
    languages=frozenset({KOTLIN}),
    requirements=always(required(KOTLIN_WARNINGS)),
    reads=(JVM_WARNING_SETTINGS.name,),
    words=Wording(
        kind="JVM compiler warnings",
        hint="build Kotlin with the Kotlin compiler plugin, whose warnings are on by default",
    ),
)


WARNINGS_AS_ERRORS = Practice(
    name=PracticeName.WARNINGS_AS_ERRORS,
    languages=JVM_LANGUAGES,
    requirements=always(*_JVM_WARNINGS_AS_ERRORS),
    any_one=True,
    reads=(JVM_WARNING_SETTINGS.name,),
    words=Wording(
        kind="warnings as errors",
        searched="the Maven or Gradle build, or CI configuration",
        hint="add -Werror to javac's compilerArgs (Kotlin: allWarningsAsErrors = true)",
    ),
)
