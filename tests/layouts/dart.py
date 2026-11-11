"""Kinds of Dart project, for tests that run a check in every layout."""

from __future__ import annotations

from tests.layouts.model import ProjectLayout

LAYOUTS = (
    ProjectLayout(
        name="Dart package",
        files={"pubspec.yaml": "name: shop\nenvironment:\n  sdk: ^3.5.0\n", "lib/shop.dart": "int total() => 0;\n"},
        languages=frozenset({"Dart"}),
        build_systems=frozenset({"pub"}),
    ),
    ProjectLayout(
        name="Flutter application",
        files={
            "pubspec.yaml": "name: shop_app\npublish_to: none\nenvironment:\n  sdk: ^3.5.0\ndependencies:\n"
            "  flutter:\n    sdk: flutter\nflutter:\n  uses-material-design: true\n",
            "lib/main.dart": "void main() {}\n",
        },
        languages=frozenset({"Dart"}),
        build_systems=frozenset({"pub"}),
    ),
)
