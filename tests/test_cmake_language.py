"""The CMake language: syntax, values, `if()` conditions and generator expressions."""

import unittest

from project_validator.build_systems.cmake.conditions import Operand, Variables, condition
from project_validator.build_systems.cmake.generator_expressions import generated, test
from project_validator.build_systems.cmake.syntax import (
    Argument,
    Block,
    CMakeSyntaxError,
    Invocation,
    Kind,
    Node,
    parse,
)
from project_validator.build_systems.cmake.values import Item, Lookup, elements, expanded
from project_validator.facts.conditions import ALWAYS, NEVER, Condition, both, either, negated, only, requiring

MSVC = only("compilers", ["msvc"])
GCC = only("compilers", ["gcc"])


def _invocation(node: Node) -> Invocation:
    if not isinstance(node, Invocation):
        raise TypeError(node)
    return node


def _block(node: Node) -> Block:
    if not isinstance(node, Block):
        raise TypeError(node)
    return node


class SyntaxTests(unittest.TestCase):
    def test_commands_and_their_arguments(self) -> None:
        [command] = parse('Add_Compile_Options(-Wall "a b" [==[x]]y]==] (c))  # comment\n')
        command = _invocation(command)
        self.assertEqual(command.name, "add_compile_options")
        self.assertEqual(
            command.arguments,
            (
                Argument("-Wall", Kind.UNQUOTED),
                Argument("a b", Kind.QUOTED),
                Argument("x]]y", Kind.BRACKET),
                Argument("(", Kind.UNQUOTED),
                Argument("c", Kind.UNQUOTED),
                Argument(")", Kind.UNQUOTED),
            ),
        )

    def test_comments_continuations_and_lines(self) -> None:
        nodes = parse('#[[ set(A 1)\n]]\nset(B "x\\\ny" [[\nz]] -Da="b c")\n')
        self.assertEqual(
            nodes,
            [
                Invocation(
                    "set",
                    (
                        Argument("B", Kind.UNQUOTED),
                        Argument("xy", Kind.QUOTED),
                        Argument("z", Kind.BRACKET),
                        Argument('-Da="b c"', Kind.UNQUOTED),
                    ),
                    3,
                )
            ],
        )

    def test_blocks_hold_what_they_enclose(self) -> None:
        [block] = parse("if(A)\n  set(X 1)\nelseif(B)\nelse()\n  foreach(I 1 2)\n  endforeach()\nendif()\n")
        block = _block(block)
        self.assertEqual([opening.name for opening, _ in block.branches], ["if", "elseif", "else"])
        self.assertEqual(block.opening.name, "if")
        [loop] = block.branches[2][1]
        loop = _block(loop)
        self.assertEqual(loop.opening.name, "foreach")

    def test_what_does_not_parse(self) -> None:
        for text, problem in (
            ("set(A", "line 1: the command's arguments are never closed"),
            ("if(A)\nset(B 1)\n", "line 1: if() is never closed with endif()"),
            ("endif()", "line 1: endif() closes nothing"),
            ('set(A "x)', "line 1: unexpected '\"'"),
            ("\n(x)", "line 2: expected a command, found '('"),
            ("set A", "line 1: expected ( after set"),
        ):
            with self.subTest(text=text), self.assertRaises(CMakeSyntaxError) as raised:
                parse(text)
            self.assertEqual(str(raised.exception), problem)


def _lookup(variables: dict[str, tuple[Item, ...]]) -> Lookup:
    return variables.get


class ValueTests(unittest.TestCase):
    def test_references_are_expanded(self) -> None:
        lookup = _lookup({"A": (Item("x"), Item("y")), "B": (Item("A"),), "A_x": (Item("deep"),)})
        self.assertEqual([value.text for value in expanded("-${A}-", lookup)], ["-x;y-"])
        self.assertEqual([value.text for value in expanded("${${B}}", lookup)], ["x;y"])
        self.assertEqual([value.text for value in expanded("${A_${B}}", lookup)], ["${A_A}"])

    def test_what_is_not_known_is_kept_as_written(self) -> None:
        lookup = _lookup({})
        self.assertEqual(
            [value.text for value in expanded("${UNSET} $ENV{HOME} $CACHE{X} ${broken", lookup)],
            ["${UNSET} $ENV{HOME} $CACHE{X} ${broken"],
        )

    def test_escapes(self) -> None:
        self.assertEqual([value.text for value in expanded(r"a\;b\n\$\{", _lookup({}))], ["ab\n${"])

    def test_a_value_set_in_some_builds_takes_each_value_in_its_builds(self) -> None:
        lookup = _lookup({"W": (Item("/W4", MSVC), Item("-Wall", GCC))})
        found = expanded("${W}", lookup)
        self.assertEqual(
            [(value.text, value.when) for value in found],
            [("/W4", MSVC), ("-Wall", GCC), ("${W}", negated(either(MSVC, GCC)))],
        )

    def test_elements_of_lists(self) -> None:
        self.assertEqual(list(elements("a;;$<$<CONFIG:Debug>:-g;-O0>;bc")), ["a", "$<$<CONFIG:Debug>:-g;-O0>", "b;c"])
        self.assertEqual(list(elements("")), [])


def _variables(
    values: dict[str, tuple[Item, ...]] | None = None, configured: frozenset[str] = frozenset()
) -> Variables:
    found = values or {}
    return Variables(value=found.get, describe=lambda name: f"<{name}>", configured=configured.__contains__)


def _holds(text: str, variables: Variables | None = None) -> Condition:
    operands = [Operand(word[1:-1], quoted=True) if word.startswith('"') else Operand(word) for word in text.split()]
    return condition(operands, variables or _variables())


class ConditionTests(unittest.TestCase):
    def test_constants(self) -> None:
        for text, expected in (
            ("ON", ALWAYS),
            ("2", ALWAYS),
            ("off", NEVER),
            ("x-NOTFOUND", NEVER),
            ('""', NEVER),
            ("", NEVER),
        ):
            with self.subTest(text=text):
                self.assertEqual(_holds(text), expected)

    def test_compilers_and_platforms(self) -> None:
        self.assertEqual(_holds("MSVC"), MSVC)
        self.assertEqual(_holds("NOT MSVC AND NOT WIN32"), both(negated(MSVC), negated(only("platforms", ["windows"]))))
        self.assertEqual(_holds("CMAKE_CXX_COMPILER_ID STREQUAL GNU"), GCC)
        self.assertEqual(
            _holds('"${CMAKE_CXX_COMPILER_ID}" MATCHES "^(GNU|MSVC)$"'), only("compilers", ["gcc", "msvc"])
        )
        self.assertEqual(
            _holds("CMAKE_CXX_COMPILER_ID MATCHES Clang"), only("compilers", ["clang", "appleclang", "other"])
        )
        self.assertEqual(
            _holds("( MSVC OR CMAKE_BUILD_TYPE STREQUAL debug )"), either(MSVC, only("configurations", ["debug"]))
        )
        self.assertEqual(_holds("GNU STREQUAL CMAKE_CXX_COMPILER_ID"), GCC)

    def test_what_is_not_understood_is_required_as_written(self) -> None:
        self.assertEqual(_holds("ENABLE_X"), requiring("<ENABLE_X>"))
        self.assertEqual(_holds("EXISTS ${X}"), requiring("EXISTS ${X}"))
        self.assertEqual(
            _holds("CMAKE_CXX_COMPILER_ID VERSION_LESS 9"), requiring("CMAKE_CXX_COMPILER_ID VERSION_LESS 9")
        )
        self.assertEqual(_holds("CMAKE_CXX_COMPILER_ID MATCHES ("), requiring("CMAKE_CXX_COMPILER_ID MATCHES ("))
        self.assertEqual(
            _holds("CMAKE_CXX_COMPILER_ID STREQUAL ${OTHER}"), requiring("CMAKE_CXX_COMPILER_ID STREQUAL ${OTHER}")
        )
        self.assertEqual(_holds("${A} STREQUAL x"), requiring("${A} STREQUAL x"))
        self.assertEqual(_holds("a EQUAL b"), requiring("a EQUAL b"))
        self.assertEqual(_holds("a IN_LIST b"), requiring("a IN_LIST b"))
        self.assertEqual(_holds('"text"'), NEVER)

    def test_comparisons_of_known_values(self) -> None:
        for text, expected in (
            ("1.2 VERSION_LESS 1.10", ALWAYS),
            ("1.2 VERSION_GREATER_EQUAL 1.10", NEVER),
            ("2 GREATER 1", ALWAYS),
            ("2 LESS_EQUAL 1", NEVER),
            ("2 GREATER_EQUAL 2", ALWAYS),
            ("3 EQUAL 3", ALWAYS),
            ("b STRGREATER a", ALWAYS),
            ("abc MATCHES ^a", ALWAYS),
            ("1.0 VERSION_EQUAL 1.0", ALWAYS),
        ):
            with self.subTest(text=text):
                self.assertEqual(_holds(text), expected)

    def test_variables_hold_in_the_builds_they_are_set_in(self) -> None:
        variables = _variables({"A": (Item("ON", MSVC), Item("OFF", GCC)), "B": (Item("${OPT}"),), "C": (Item("x"),)})
        self.assertEqual(_holds("A", variables), MSVC)
        self.assertEqual(_holds("B", variables), requiring("<OPT>"))
        self.assertEqual(_holds("C", variables), ALWAYS)
        self.assertEqual(_holds("C STREQUAL x", variables), ALWAYS)
        self.assertEqual(_holds("${C}", variables), requiring("<C>"))

    def test_defined(self) -> None:
        variables = _variables({"SET": (Item("1"),), "SOMETIMES": (Item("1", MSVC),)}, frozenset({"OPTION"}))
        self.assertEqual(_holds("DEFINED SET", variables), ALWAYS)
        self.assertEqual(_holds("DEFINED OPTION", variables), ALWAYS)
        self.assertEqual(_holds("DEFINED UNSET", variables), requiring("DEFINED UNSET"))
        self.assertEqual(_holds("DEFINED SOMETIMES", variables), either(MSVC, requiring("DEFINED SOMETIMES")))


class GeneratorExpressionTests(unittest.TestCase):
    def test_conditional_values(self) -> None:
        self.assertEqual(
            [(value.text, value.when) for value in generated("$<$<CONFIG:Debug,RelWithDebInfo>:-g>")],
            [
                ("-g", only("configurations", ["debug", "relwithdebinfo"])),
                ("", negated(only("configurations", ["debug", "relwithdebinfo"]))),
            ],
        )
        self.assertEqual(generated("$<0:-x>")[0].text, "")
        self.assertEqual([value.text for value in generated("$<1:-x>")], ["-x"])

    def test_tests(self) -> None:
        for text, expected in (
            ("$<CXX_COMPILER_ID:MSVC>", MSVC),
            ("$<NOT:$<C_COMPILER_ID:GNU>>", negated(GCC)),
            (
                "$<AND:$<COMPILE_LANGUAGE:CXX>,$<PLATFORM_ID:Linux>>",
                both(only("languages", ["C++"]), only("platforms", ["linux"])),
            ),
            ("$<OR:$<CXX_COMPILER_ID:MSVC>,$<CXX_COMPILER_ID:GNU>>", either(MSVC, GCC)),
            ("$<COMPILE_LANG_AND_ID:CXX,GNU,MSVC>", both(only("languages", ["C++"]), either(MSVC, GCC))),
            ("$<BOOL:${ENABLE}>", requiring("ENABLE")),
            ("$<BOOL:OFF>", NEVER),
            ("$<BOOL:yes>", ALWAYS),
            ("$<STREQUAL:a,a>", ALWAYS),
            ("$<STREQUAL:a,b>", NEVER),
            ("$<STREQUAL:${A},b>", requiring("$<STREQUAL:${A},b>")),
            ("$<TARGET_EXISTS:x>", requiring("$<TARGET_EXISTS:x>")),
            ("plain", requiring("plain")),
            ("1", ALWAYS),
        ):
            with self.subTest(text=text):
                self.assertEqual(test(text), expected)

    def test_values(self) -> None:
        for text, expected in (
            ("$<BUILD_INTERFACE:-Wall>", ["-Wall"]),
            ("$<INSTALL_INTERFACE:-Wall>", [""]),
            ("a$<SEMICOLON>b$<COMMA>c$<ANGLE-R>", ["a;b,c>"]),
            ("$<TARGET_FILE:app>", ["$<TARGET_FILE:app>"]),
            ("$<unclosed", ["$<unclosed"]),
            ("$<IF:$<CXX_COMPILER_ID:MSVC>,/W4,-Wall>", ["/W4", "-Wall"]),
            ("$<CONFIG:Debug>", ["1", "0"]),
        ):
            with self.subTest(text=text):
                self.assertEqual([value.text for value in generated(text)], expected)
