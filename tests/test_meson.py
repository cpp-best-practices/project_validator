"""Reading Meson projects: syntax, values, evaluation, and run targets."""

from __future__ import annotations

import unittest
from unittest import mock

from project_validator.build_systems import meson
from project_validator.build_systems.meson import evaluation, syntax
from project_validator.build_systems.meson.operations import binary, equal, indexed, method, text_of, written
from project_validator.build_systems.meson.values import (
    FALSE,
    TRUE,
    Array,
    Compiler,
    Dictionary,
    Object,
    Symbol,
    Truth,
    Unknown,
    holds,
    single,
    truth,
)
from project_validator.facts import Command, Fact, Setting
from project_validator.facts import Unknown as UnknownFact
from project_validator.facts.build import Applies, BuildSetting, CompilerOption
from project_validator.facts.conditions import ALWAYS, DIMENSIONS, NEVER, both, negated, only, requiring
from tests.support import github_job, make_context, temp_project

ANY = Applies()
MSVC = only("compilers", ["msvc"])


def _lines(*lines: str) -> str:
    return "".join(f"{line}\n" for line in lines)


def _facts(*lines: str, **files: str) -> tuple[Fact, ...]:
    return meson._evaluated({"meson.build": _lines(*lines), **files}).facts


def _options(found: tuple[Fact, ...]) -> list[tuple[str, str | None, Applies, bool]]:
    return [
        (fact.option, fact.target, fact.applies, fact.linking) for fact in found if isinstance(fact, CompilerOption)
    ]


def _settings(found: tuple[Fact, ...]) -> list[tuple[str, str, str | None, bool]]:
    return [(fact.name, fact.value, fact.target, fact.default) for fact in found if isinstance(fact, BuildSetting)]


def _builds(applies: Applies) -> str:
    dimensions = ("compilers", "platforms", "configurations", "languages", "requires")
    return " ".join(f"{name}={','.join(sorted(values))}" for name in dimensions if (values := getattr(applies, name)))


def _described(found: tuple[Fact, ...]) -> list[str]:
    """Each option: itself, its target, whether it is a link option, and its builds."""
    options = (fact for fact in found if isinstance(fact, CompilerOption))
    return [
        f"{fact.option} {fact.target} {'link' if fact.linking else 'compile'} {_builds(fact.applies)}"
        for fact in options
    ]


GNU = "compilers=appleclang,clang,flang,gcc,intel"
BRANCHES = [
    # Meson's default warning_level (1), and werror=true.
    f"-Wall None compile {GNU}",
    "/W2 None compile compilers=msvc",
    f"-Werror None compile {GNU}",
    "/WX None compile compilers=msvc",
    "/W4 None compile compilers=msvc languages=C++",
    f"-Wall None compile {GNU} languages=C,C++ requires=the compiler accepts -Wall",
    f"-a None compile {GNU} languages=C++ requires=the compiler accepts -a",
    f"-b None compile {GNU} languages=C++ requires=NOT the compiler accepts -a,the compiler accepts -b",
    "/guard:cf None link platforms=windows configurations=minsizerel,other,release,relwithdebinfo",
    "-fhardened None compile requires=the compiler accepts -fhardened",
]
NOT_MSVC = "compilers=" + ",".join(sorted(set(DIMENSIONS["compilers"]) - {"msvc"}))
VARIABLES = [
    f"-fstack-protector-strong app-cli compile {NOT_MSVC} languages=C",
    f"-D_FORTIFY_SOURCE=2 app-cli compile {NOT_MSVC} languages=C requires=get_option('hardening')",
    "/sdl app-cli compile compilers=msvc languages=C",
    "-pie app-cli link ",
    "-g None compile languages=C++",
    "/sdl None compile compilers=msvc languages=C",
]


STATEMENTS = _lines(
    "﻿x = 1  # one",
    "x += [2, 0x10, 0o7, 0b1, 010]",
    "if not x",
    "elif x in y and z not in w or -x > 1",
    "else",
    "endif",
    "foreach k, v : {'a': 1,}",
    "  break",
    "  continue",
    "endforeach",
    "f(a, b: 'c', d: f'''@x@''')[0].m(e)",
    "y = c ? 'a\\tb' : '''raw\\t'''",
    "z = (1 + 2) * 3 / 4 % 5 - 6",
)


EXPRESSIONS = (
    "version = '1'",
    "x = f'v@version@'",
    "parts = 'a,b'.split(',')",
    "d = {'k': 'v', 1: 'skipped'}",
    "foreach key, value : d",
    "  add_project_arguments('-D' + key + '=' + value, language: 'c')",
    "endforeach",
    "foreach part : parts",
    "  add_project_arguments('-D' + part.to_upper(), language: 'c')",
    "endforeach",
    "foreach one : 'single'",
    "  add_project_arguments(one, language: 'c')",
    "endforeach",
    "add_project_arguments(x, parts[0], d['k'], -1 > 0 ? '-yes' : '-no', language: 'c')",
    "add_project_arguments(is_variable('x') ? '-defined' : '-undefined', unknown, language: 'c')",
    "add_project_arguments(not true ? '-a' : '-b', parts[5], language: 'c')",
    "if true",
    "elif unknown",
    "  add_project_arguments('-never', language: 'c')",
    "endif",
    "break",
    "maybe = 'a'",
    "if unknown",
    "  maybe = 'b'",
    "endif",
    "add_project_arguments(f'@maybe@', language: 'c')",
)


class SyntaxTests(unittest.TestCase):
    def test_statements(self) -> None:
        nodes = syntax.parse(STATEMENTS)
        kinds = ["Assignment", "Assignment", "If", "Foreach", "Statement", "Assignment", "Assignment"]
        self.assertEqual([type(node).__name__ for node in nodes], kinds)
        conditional = nodes[2]
        assert isinstance(conditional, syntax.If)  # noqa: S101
        self.assertEqual([condition is None for condition, _ in conditional.branches], [False, False, True])
        loop = nodes[3]
        assert isinstance(loop, syntax.Foreach)  # noqa: S101
        self.assertEqual((loop.names, [type(node).__name__ for node in loop.body]), (("k", "v"), ["Jump", "Jump"]))
        choice = nodes[5]
        assert isinstance(choice, syntax.Assignment)  # noqa: S101
        self.assertEqual(written(choice.value), "c ? 'a\\tb' : 'raw\\\\t'")
        self.assertEqual(written(syntax.Index(syntax.Name("a"), syntax.Literal(1))), "...")

    def test_what_does_not_parse(self) -> None:
        for text, problem in (
            ("x = ~", "line 1: unexpected '~'"),
            ("if x\n", "line 2: expected elif or else or endif"),
            ("x y", "line 1: unexpected 'y'"),
            ("foreach 1 : x\nendforeach", "line 1: expected a name, found '1'"),
            ("f(a", "line 1: expected ')', found '\\n'"),
            ("x = [1 2]", "line 1: expected ']', found '2'"),
            ("x = )", "line 1: unexpected ')'"),
        ):
            with self.subTest(text=text), self.assertRaises(syntax.MesonSyntaxError) as raised:
                syntax.parse(text)
            self.assertEqual(str(raised.exception), problem)

    def test_deep_nesting_is_a_syntax_error(self) -> None:
        for text in ("x = " + "(" * 5000 + "1" + ")" * 5000, "if true\n" * 5000 + "endif\n" * 5000, "{" * 5000):
            with self.subTest(text=text[:12]), self.assertRaisesRegex(syntax.MesonSyntaxError, "nested too deeply"):
                syntax.parse(text)


class DepthTests(unittest.TestCase):
    def test_a_long_chain_is_unknown_not_a_crash(self) -> None:
        for chain in ("'a'" + " + 'a'" * 3000, "'a'" + ".strip()" * 3000):
            with self.subTest(chain=chain[:20]):
                found = _facts(f"x = {chain}")
                self.assertTrue(
                    any(isinstance(fact, UnknownFact) and "nested too deeply" in fact.reason for fact in found)
                )


class ValueTests(unittest.TestCase):
    def test_truth(self) -> None:
        self.assertEqual(truth(TRUE), ALWAYS)
        self.assertEqual(truth(Unknown("get_option('x')")), requiring("get_option('x')"))
        self.assertEqual(truth(""), NEVER)
        self.assertEqual(truth("x"), ALWAYS)
        self.assertEqual(holds([(TRUE, MSVC), (FALSE, negated(MSVC))]), MSVC)

    def test_operations(self) -> None:
        compiler = Symbol(evaluation.LANGUAGE, "x")
        self.assertEqual(equal(Symbol(meson.evaluation.LANGUAGE, "cc"), "cpp"), only("languages", ["C++"]))
        self.assertEqual(equal(Unknown("a"), 1), requiring("a == 1"))
        self.assertEqual(equal(TRUE, Truth(MSVC)), MSVC)
        self.assertEqual(binary("!=", 1, 2, ""), TRUE)
        self.assertEqual(binary("not in", "a", Array((("a", MSVC),)), ""), Truth(negated(MSVC)))
        self.assertEqual(
            binary("+", Dictionary((("a", 1),)), Dictionary((("b", 2),)), ""), Dictionary((("a", 1), ("b", 2)))
        )
        self.assertEqual(binary("+", 1, 2, ""), 3)
        self.assertEqual(binary("+", 1, "a", ""), Unknown("1 + a"))
        self.assertEqual(
            [binary(operator, 7, 2, "") for operator in ("-", "*", "/", "%", "<", ">=")], [5, 14, 3, 1, FALSE, TRUE]
        )
        self.assertEqual(binary("/", 1, 0, "1 / 0"), Unknown("1 / 0"))
        self.assertEqual(binary("<", compiler, 2, "x < 2"), Unknown("x < 2"))
        self.assertEqual(indexed(Array(((1, ALWAYS),)), 0, "a"), 1)
        self.assertEqual(indexed(Array(((1, MSVC),)), 0, "a"), Unknown("a[...]"))
        self.assertEqual(indexed(Dictionary((("k", 1),)), "x", "d"), Unknown("d['x']"))
        self.assertEqual(
            [text_of(value) for value in (Truth(MSVC), FALSE, Array(((1, ALWAYS),)), Object("program", "tidy"))],
            ["?", "false", "1", "tidy"],
        )

    def test_methods(self) -> None:
        def call(name: str, *arguments: str) -> syntax.Call:
            return syntax.Call(name, syntax.Arguments(tuple(syntax.Literal(argument) for argument in arguments)))

        def run(target: object, name: str, *arguments: str) -> object:
            values = [(argument, ALWAYS) for argument in arguments]
            [(value, _)] = method(target, call(name, *arguments), values)  # type: ignore[arg-type]
            return value

        self.assertEqual(run("a-@0@", "format", "b"), "a-b")
        self.assertEqual(
            [run("abc", name, "a") for name in ("startswith", "endswith", "contains")], [TRUE, FALSE, TRUE]
        )
        self.assertEqual(run(",", "join", "a", "b"), "a,b")
        self.assertEqual(run(" A ", "strip"), "A")
        self.assertEqual(run("a b", "split"), Array((("a", ALWAYS), ("b", ALWAYS))))
        self.assertEqual(run("a", "underscorify"), Unknown("'a'.underscorify()"))
        self.assertEqual(run(Array((("a", ALWAYS),)), "contains", "a"), TRUE)
        self.assertEqual(run(Array(), "length"), Unknown("length()"))
        self.assertEqual(run(Compiler("cpp"), "version"), Unknown("version()"))
        self.assertEqual(run(Object("machine"), "cpu_family"), Unknown("cpu_family()"))
        self.assertEqual(run(Object("meson"), "is_subproject"), FALSE)
        self.assertEqual(single(1), [(1, ALWAYS)])


class EvaluationTests(unittest.TestCase):
    def test_branches_by_compiler_platform_and_build_type(self) -> None:
        found = _facts(
            "project('app', 'cpp', default_options: ['cpp_std=c++20', 'werror=true', 'not a pair'])",
            "cc = meson.get_compiler('cpp')",
            "if cc.get_id() == 'msvc'",
            "  add_project_arguments('/W4', language: 'cpp')",
            "elif cc.get_argument_syntax() == 'gcc'",
            "  add_project_arguments(cc.get_supported_arguments('-Wall'), language: ['c', 'cpp'])",
            "  add_project_arguments(cc.first_supported_argument(['-a', '-b']), language: 'cpp')",
            "endif",
            "if host_machine.system() == 'windows' and get_option('buildtype') != 'debug'",
            "  add_global_link_arguments('/guard:cf')",
            "endif",
            "if cc.has_argument('-fhardened')",
            "  add_global_arguments('-fhardened')",
            "endif",
        )
        self.assertEqual(_described(found), BRANCHES)
        self.assertEqual(
            _settings(found),
            [("warning_level", "1", None, True), ("cpp_std", "c++20", None, True), ("werror", "true", None, True)],
        )

    def test_variables_hold_each_value_in_the_builds_it_is_set_in(self) -> None:
        found = _facts(
            "flags = ['-fstack-protector-strong']",
            "if get_option('hardening')",
            "  flags += ['-D_FORTIFY_SOURCE=2']",
            "endif",
            "if meson.get_compiler('c').get_id() == 'msvc'",
            "  flags = ['/sdl']",
            "endif",
            "name = 'app'",
            "name += '-cli'",
            "count = 1",
            "count += 2",
            "executable(name, c_args: flags, link_args: ['-pie'], override_options: {'c_std': 'c17'})",
            "executable(cpp_args: '-g', install: true)",
            "if meson.get_compiler('c').get_id() == 'msvc'",
            "  foreach flag : flags",
            "    add_project_arguments(flag, language: 'c')",
            "  endforeach",
            "endif",
        )
        self.assertEqual(_described(found), VARIABLES)
        self.assertEqual(_settings(found), [("c_std", "c17", "app-cli", False)])

    def test_expressions(self) -> None:
        found = _facts(*EXPRESSIONS)
        self.assertEqual(
            [option for option, *_ in _options(found)],
            ["-Dk=v", "-DA", "-DB", "single", "v1", "a", "v", "-no", "-defined", "-b", "@maybe@"],
        )

    def test_subdirectories_tests_and_options(self) -> None:
        found = meson._evaluated(
            {
                "meson.build": _lines(
                    "project('app')", "subdir('src')", "subdir('missing')", "if false", "  subdir('src')", "endif"
                ),
                "src/meson.build": _lines("test('t', executable('t'))"),
                "examples/meson.build": _lines("add_global_arguments('-example')"),
                "meson.options": _lines("option('hardening', type: 'boolean', value: true)", "option()"),
            }
        ).facts
        tests = [fact.origin.path for fact in found if isinstance(fact, Setting) and fact.key != "guard"]
        self.assertEqual(tests, ["src/meson.build"])
        # The top-level project() passes Meson's default warning level; examples/ has no project().
        self.assertEqual([option for option, *_ in _options(found)], ["-Wall", "/W2", "-example"])
        self.assertEqual(_settings(found), [("warning_level", "1", None, True), ("hardening", "true", None, True)])

    def test_facts_are_placed_at_the_statement_they_come_from(self) -> None:
        """A guard is placed at its own `if` or `elif`, not at the statement before it."""
        found = _facts(
            "project('x', default_options: ['warning_level=3'])",
            "if get_option('a')",
            "  add_project_arguments('-Wall',",
            "    language: 'c')",
            "elif not meson.is_subproject()",
            "  test('t', exe)",
            "endif",
        )
        placed = sorted(
            {
                (type(fact).__name__, str(fact.origin))
                for fact in found
                if isinstance(fact, (Setting, BuildSetting, CompilerOption))
            }
        )
        self.assertEqual(
            placed,
            [
                ("BuildSetting", "meson.build:1:1 (project)"),
                ("CompilerOption", "meson.build:1:1 (project)"),
                ("CompilerOption", "meson.build:3:3 (add_project_arguments)"),
                ("Setting", "meson.build:2:1 (if)"),
                ("Setting", "meson.build:5:1 (elif)"),
                ("Setting", "meson.build:6:3 (test)"),
            ],
        )

    def test_what_cannot_be_evaluated_is_unknown(self) -> None:
        [unknown] = (fact for fact in _facts("if x") if isinstance(fact, UnknownFact))
        self.assertEqual(
            (unknown.subject, unknown.reason, str(unknown.origin)),
            ("the Meson file meson.build", "line 2: expected elif or else or endif", "meson.build:2"),
        )
        with mock.patch.object(evaluation, "MOST_STATEMENTS", 2):
            [unknown] = (fact for fact in _facts("a = 1", "b = 2", "c = 3") if isinstance(fact, UnknownFact))
            # At the limit, every statement is evaluated (upstream #303).
            self.assertEqual([fact for fact in _facts("a = 1", "b = 2") if isinstance(fact, UnknownFact)], [])
        self.assertEqual(unknown.reason, "evaluation stopped after 2 statements")

    def test_declared_languages(self) -> None:
        self.assertEqual(
            meson.declared_languages("project('app', 'c', ['cpp', 'rust'], version: '1')"), ("c", "cpp", "rust")
        )
        self.assertEqual(meson.declared_languages("x = 1"), ())
        self.assertEqual(meson.declared_languages("project('app', languages)"), ())
        self.assertEqual(meson.declared_languages("project("), ())


RUN_TARGETS = {
    "meson.build": _lines(
        "project('app')",
        "tidy = find_program('clang-tidy')",
        "run_target('lint', command: [tidy, '-p', meson.project_build_root()])",
        "run_target('empty')",
    )
}


def _expanded(line: str) -> list[tuple[str, ...]]:
    with temp_project({**RUN_TARGETS, **github_job("lint", line)}) as root:
        facts = make_context(root).facts
    return [fact.argv for fact in facts.of(Command) if fact.via]


class RunTargetTests(unittest.TestCase):
    def test_compiling_a_run_target_runs_its_command(self) -> None:
        for line in ("meson compile -C build lint", "ninja -C build lint"):
            with self.subTest(line=line):
                self.assertEqual(_expanded(line), [("clang-tidy", "-p", "meson.project_build_root()")])

    def test_other_commands_are_not_expanded(self) -> None:
        for line in ("meson setup build", "ninja -C build", "make lint"):
            with self.subTest(line=line):
                self.assertEqual(_expanded(line), [])

    def test_a_project_is_evaluated_once(self) -> None:
        with temp_project(RUN_TARGETS) as root:
            context = make_context(root)
            self.assertIs(meson.meson_project(context), meson.meson_project(context))
        self.assertEqual(both(), ALWAYS)


class GuardTests(unittest.TestCase):
    def test_what_each_if_tests_is_recorded_as_written(self) -> None:
        found = _facts(
            "project('app', 'cpp')",
            "if not meson.is_subproject()",
            "  message('top level')",
            "elif get_option('tests')",
            "  message('tests')",
            "else",
            "  message('neither')",
            "endif",
        )
        guards = [(fact.tool, fact.value) for fact in found if isinstance(fact, Setting) and fact.key == "guard"]
        self.assertEqual(guards, [("Meson", "not meson.is_subproject()"), ("Meson", "get_option('tests')")])


class OperationEdgeTests(unittest.TestCase):
    def test_in_needs_an_array(self) -> None:
        self.assertEqual(binary("in", "a", "abc", "a in abc"), Unknown("a in abc"))
        self.assertEqual(binary("in", "a", Array((("a", ALWAYS),)), ""), TRUE)

    def test_adding_to_an_array_appends_an_item_or_each_item(self) -> None:
        self.assertEqual(binary("+", Array(((1, ALWAYS),)), 2, ""), Array(((1, ALWAYS), (2, ALWAYS))))
        self.assertEqual(binary("+", Array(((1, ALWAYS),)), Array(((2, MSVC),)), ""), Array(((1, ALWAYS), (2, MSVC))))

    def test_comparing_with_a_truth_takes_its_condition_from_either_side(self) -> None:
        self.assertEqual(equal(Truth(MSVC), TRUE), MSVC)
        self.assertEqual(equal(TRUE, Truth(MSVC)), MSVC)
        self.assertEqual(equal(FALSE, Truth(MSVC)), negated(MSVC))

    def test_indexing_needs_a_matching_container_and_key(self) -> None:
        self.assertEqual(indexed(Dictionary((("k", 1),)), "k", "d"), 1)
        self.assertEqual(indexed(Array(((1, ALWAYS),)), "k", "a"), Unknown("a[...]"))
        self.assertEqual(indexed("text", 0, "s"), Unknown("s[...]"))

    def test_expressions_are_written_as_they_read(self) -> None:
        for text in ("a ? b : c", "not a", "a not in b", "a in b", "true", "false", "a or b and c"):
            with self.subTest(text=text):
                [statement] = syntax.parse(f"x = {text}\n")
                if not isinstance(statement, syntax.Assignment):
                    self.fail(f"not an assignment: {statement}")
                self.assertEqual(written(statement.value), text)


class EvaluationEdgeTests(unittest.TestCase):
    def test_is_variable_holds_only_for_an_assigned_variable(self) -> None:
        found = _facts(
            "project('app')",
            "x = 1",
            "if is_variable('x')",
            "  add_global_arguments('-set')",
            "endif",
            "if is_variable('y')",
            "  add_global_arguments('-unset')",
            "endif",
        )
        options = [option for option, *_ in _options(found)]
        self.assertIn("-set", options)
        self.assertNotIn("-unset", options)

    def test_a_subdirectory_reached_twice_is_evaluated_once(self) -> None:
        found = meson._evaluated(
            {
                "meson.build": _lines("project('app')", "subdir('src')", "subdir('src')"),
                "src/meson.build": _lines("add_global_arguments('-src')"),
            }
        ).facts
        self.assertEqual([option for option, *_ in _options(found)].count("-src"), 1)

    def test_a_subdirectory_keeps_the_condition_it_is_reached_under(self) -> None:
        found = meson._evaluated(
            {
                "meson.build": _lines(
                    "project('app')", "if meson.get_compiler('cpp').get_id() == 'msvc'", "  subdir('src')", "endif"
                ),
                "src/meson.build": _lines("add_global_arguments('-src')"),
            }
        ).facts
        [applies] = [applies for option, _, applies, _ in _options(found) if option == "-src"]
        self.assertEqual(applies.compilers, frozenset({"msvc"}))


class RunTargetEdgeTests(unittest.TestCase):
    def test_a_run_target_without_a_command_runs_nothing(self) -> None:
        self.assertEqual(_expanded("ninja -C build empty"), [])

    def test_a_run_target_without_a_name_is_no_target(self) -> None:
        """Meson rejects a run_target() with a command but no name; reading one records no target (upstream
        #301)."""
        with temp_project({"meson.build": "project('app')\nrun_target(command: ['clang-tidy'])\n"}) as root:
            self.assertEqual(dict(meson.meson_project(make_context(root)).targets), {})

    def test_an_executable_the_project_builds_runs_by_its_name(self) -> None:
        """`run_target('gen', command: [exe, '--all'])` runs the executable `exe = executable('tool', ...)` builds:
        the command's word is the target's name, as a found program's is (upstream #302)."""
        build = "project('app')\nexe = executable('tool', 'tool.c')\nrun_target('gen', command: [exe, '--all'])\n"
        with temp_project({"meson.build": build}) as root:
            [(argv, _, _)] = meson.meson_project(make_context(root)).targets["gen"]
        self.assertEqual(argv, ("tool", "--all"))
