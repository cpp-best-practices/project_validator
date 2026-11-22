from __future__ import annotations

import unittest

from project_validator.facts.nix_syntax import attributes


def _found(text: str) -> dict[tuple[str, ...], str]:
    return dict(attributes(text))


class AttributeTests(unittest.TestCase):
    def test_a_module_s_nested_and_dotted_attributes_are_its_paths(self) -> None:
        text = '{ pkgs, ... }:\n{\n  a.b = true;\n  c = {\n    d = 1;\n    e.f = "x";\n  };\n}\n'
        self.assertEqual(_found(text), {("a", "b"): "true", ("c", "d"): "1", ("c", "e", "f"): '"x"'})

    def test_a_let_before_an_attribute_set_is_passed_over(self) -> None:
        """cachix/devenv's `git-hooks = let modulePath = "^src/modules/"; in { ... }`."""
        text = (
            '{\n  git-hooks =\n    let\n      modulePath = "^src/modules/";\n    in\n'
            "    {\n      hooks.x.enable = true;\n    };\n}\n"
        )
        self.assertEqual(_found(text), {("git-hooks", "hooks", "x", "enable"): "true"})

    def test_strings_and_comments_hide_their_braces_and_semicolons(self) -> None:
        text = (
            '{\n  # a comment; with { braces\n  a = "${b}.*\\\\.nix$; }";\n  /* c = { ; */\n'
            "  d = ''\n    e = { ;\n  '';\n  f = true;\n}\n"
        )
        found = _found(text)
        self.assertEqual(found[("f",)], "true")
        self.assertEqual(set(found), {("a",), ("d",), ("f",)})

    def test_a_quoted_attribute_name_is_its_text(self) -> None:
        self.assertEqual(_found('{ hooks."ruff-format".enable = true; }'), {("hooks", "ruff-format", "enable"): "true"})

    def test_inherit_lists_and_applications_are_values_not_attribute_sets(self) -> None:
        text = "{ inherit pkgs; a = [ { b = 1; } ]; c = lib.mkIf x { d = true; }; e = true; }"
        found = _found(text)
        self.assertEqual(found[("e",)], "true")
        self.assertNotIn(("a", "b"), found)
        self.assertNotIn(("c", "d"), found)

    def test_text_that_is_no_attribute_set_has_no_attributes(self) -> None:
        for text in ("", "pkgs: pkgs.hello", "{ a = ", "}", "{ a = { b = 1; }"):
            with self.subTest(text=text):
                self.assertIsInstance(_found(text), dict)


if __name__ == "__main__":
    unittest.main()
