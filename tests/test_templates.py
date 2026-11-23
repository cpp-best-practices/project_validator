"""The shared template engine: text with references, parsed by a language's syntax and substituted by one rule."""

from __future__ import annotations

import re
import unittest

from project_validator.templates import SHELL, Reference, Syntax, Template, known

BRACES = Syntax(re.compile(r"\{(?P<name>\w+)(?::(?P<default>[^{}]*))?\}"))


class ParseTests(unittest.TestCase):
    def test_text_is_literal_parts_and_references(self) -> None:
        self.assertEqual(
            SHELL.parse("cc ${CFLAGS} -o $OUT"),
            Template(("cc ", Reference("CFLAGS", "${CFLAGS}"), " -o ", Reference("OUT", "$OUT"))),
        )

    def test_a_syntax_with_defaults_keeps_them(self) -> None:
        self.assertEqual(BRACES.parse("{posargs:tests}").parts, (Reference("posargs", "{posargs:tests}", "tests"),))

    def test_a_template_that_is_one_reference_is_whole(self) -> None:
        """The shell splits a word that is one unquoted variable into the words of its value."""
        self.assertEqual(SHELL.parse("$CABAL").whole, Reference("CABAL", "$CABAL"))
        self.assertIsNone(SHELL.parse("$CABAL-v").whole)
        self.assertIsNone(SHELL.parse("cabal").whole)

    def test_the_reference_a_template_starts_with_is_leading(self) -> None:
        """A command whose program is a variable: `$CC -c x.c`."""
        self.assertEqual(SHELL.parse("$CC -c x.c").leading, Reference("CC", "$CC"))
        self.assertIsNone(SHELL.parse("cc $CFLAGS").leading)
        self.assertIsNone(SHELL.parse("").leading)

    def test_an_unbalanced_brace_is_no_reference(self) -> None:
        self.assertEqual(SHELL.parse("${A").references, ())
        self.assertEqual(SHELL.parse("$A}").parts, (Reference("A", "$A"), "}"))


class SubstituteTests(unittest.TestCase):
    def test_a_reference_with_a_value_is_replaced_and_one_without_stays_as_written(self) -> None:
        self.assertEqual(SHELL.substituted("$A ${B} $C", known({"A": "1", "B": "2"})), "1 2 $C")

    def test_the_lookup_sees_the_reference_and_its_default(self) -> None:
        self.assertEqual(
            BRACES.substituted("pytest {posargs:tests} {x}", lambda ref: ref.default or "."), "pytest tests ."
        )

    def test_values_that_refer_on_are_substituted_as_many_rounds_as_asked(self) -> None:
        values = known({"A": "$B", "B": "$C", "C": "done"})
        self.assertEqual(SHELL.substituted("$A", values), "$B")
        self.assertEqual(SHELL.substituted("$A", values, rounds=10), "done")

    def test_a_value_that_refers_to_itself_stops_at_the_rounds_asked(self) -> None:
        self.assertEqual(SHELL.substituted("$A", known({"A": "x$A"}), rounds=3), "xxx$A")


if __name__ == "__main__":
    unittest.main()
