"""Tests of tests/changed_mutants.py: the mutmut mutants of the functions a diff touches."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import changed_mutants
from tests.changed_mutants import changed_lines, mutant_patterns, patterns_for

DIFF = """\
diff --git a/project_validator/a.py b/project_validator/a.py
index 1111111..2222222 100644
--- a/project_validator/a.py
+++ b/project_validator/a.py
@@ -3 +3 @@ def f():
-    return 1
+    return 2
@@ -10,2 +10,3 @@ class C:
-    x = 1
-    y = 2
+    x = 10
+    y = 20
+    z = 30
diff --git a/project_validator/gone.py b/project_validator/gone.py
deleted file mode 100644
index 3333333..0000000
--- a/project_validator/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def g():
-    return 1
diff --git a/project_validator/d.py b/project_validator/d.py
index 4444444..5555555 100644
--- a/project_validator/d.py
+++ b/project_validator/d.py
@@ -7,2 +6,0 @@ def h():
-    a = 1
-    b = 2
diff --git a/project_validator/new.py b/project_validator/new.py
new file mode 100644
index 0000000..6666666
--- /dev/null
+++ b/project_validator/new.py
@@ -0,0 +1,2 @@
+def n():
+    return 1
diff --git a/project_validator/top.py b/project_validator/top.py
index 7777777..8888888 100644
--- a/project_validator/top.py
+++ b/project_validator/top.py
@@ -1 +0,0 @@
-import os
diff --git a/project_validator/sp ace.py b/project_validator/sp ace.py
index 9999999..aaaaaaa 100644
--- a/project_validator/sp ace.py\t
+++ b/project_validator/sp ace.py\t
@@ -2 +2 @@
-x = 1
+x = 2
"""

SOURCE = '''\
"""A module."""

CONSTANT = 1


def top(x):
    return x + 1


@decorated
def with_decorator(x):
    def inner(y):
        return y
    return inner(x)


class Klass:
    attribute = 2

    def method(self):
        return 1

    @property
    def prop(self):
        return 2

    class Nested:
        def nested_method(self):
            return 3

    @staticmethod
    def static():
        return 5

    @functools.cache
    def cached(self):
        return 6

    def __new__(cls):
        return object.__new__(cls)


async def coroutine():
    return 4


def topology():
    return 7


class Colour(enum.Enum):
    RED = 1

    def __init__(self, value):
        self.v = value

    def describe(self):
        return self.name
'''


class ChangedLinesTests(unittest.TestCase):
    def test_added_and_changed_lines_are_numbered_in_the_new_file(self) -> None:
        self.assertEqual(changed_lines(DIFF)["project_validator/a.py"], {3, 10, 11, 12})

    def test_a_deleted_file_has_no_lines(self) -> None:
        self.assertNotIn("project_validator/gone.py", changed_lines(DIFF))

    def test_a_pure_deletion_touches_the_lines_around_it(self) -> None:
        self.assertEqual(changed_lines(DIFF)["project_validator/d.py"], {6, 7})

    def test_a_deletion_at_the_top_touches_the_first_line(self) -> None:
        self.assertEqual(changed_lines(DIFF)["project_validator/top.py"], {1})

    def test_a_new_file_has_every_line(self) -> None:
        self.assertEqual(changed_lines(DIFF)["project_validator/new.py"], {1, 2})

    def test_a_name_with_a_space_loses_the_tab_git_appends(self) -> None:
        self.assertEqual(changed_lines(DIFF)["project_validator/sp ace.py"], {2})

    def test_no_diff_no_lines(self) -> None:
        self.assertEqual(changed_lines(""), {})


class MutantPatternsTests(unittest.TestCase):
    def patterns(self, *lines: int) -> list[str]:
        return mutant_patterns("project_validator/pkg/mod.py", SOURCE, lines)

    def test_a_line_in_a_function_selects_its_mutants_and_its_tests(self) -> None:
        self.assertEqual(self.patterns(7), ["project_validator.pkg.mod.x_top*"])

    def test_a_decorated_function_is_not_mutated(self) -> None:
        self.assertEqual(self.patterns(10, 11, 14), [])

    def test_a_method_is_named_with_its_class(self) -> None:
        self.assertEqual(self.patterns(21), ["project_validator.pkg.mod.xǁKlassǁmethod*"])

    def test_a_property_is_not_mutated(self) -> None:
        self.assertEqual(self.patterns(23, 25), [])

    def test_a_static_method_counts_from_its_decorator(self) -> None:
        self.assertEqual(self.patterns(31), ["project_validator.pkg.mod.xǁKlassǁstatic*"])

    def test_a_dotted_decorator_is_not_mutated(self) -> None:
        self.assertEqual(self.patterns(36), [])

    def test_new_is_never_mutated(self) -> None:
        self.assertEqual(self.patterns(40), [])

    def test_module_level_and_class_body_lines_select_nothing(self) -> None:
        self.assertEqual(self.patterns(1, 3, 19), [])

    def test_a_method_of_a_nested_class_is_not_mutated(self) -> None:
        self.assertEqual(self.patterns(28), [])

    def test_a_coroutine_is_a_function(self) -> None:
        self.assertEqual(self.patterns(44), ["project_validator.pkg.mod.x_coroutine*"])

    def test_an_enum_init_is_not_mutated_but_its_other_methods_are(self) -> None:
        self.assertEqual(self.patterns(54), [])
        self.assertEqual(self.patterns(58), ["project_validator.pkg.mod.xǁColourǁdescribe*"])

    def test_patterns_are_unique_and_sorted(self) -> None:
        self.assertEqual(
            self.patterns(21, 7, 6, 8, 48),
            [
                "project_validator.pkg.mod.x_top*",
                "project_validator.pkg.mod.x_topology*",
                "project_validator.pkg.mod.xǁKlassǁmethod*",
            ],
        )

    def test_a_package_init_is_named_by_its_package(self) -> None:
        self.assertEqual(
            mutant_patterns("project_validator/pkg/__init__.py", SOURCE, [7]), ["project_validator.pkg.x_top*"]
        )

    def test_a_file_that_does_not_parse_selects_nothing(self) -> None:
        self.assertEqual(mutant_patterns("project_validator/bad.py", "def (", [1]), [])


class PatternsForTests(unittest.TestCase):
    def test_reads_each_changed_file_once_and_skips_missing_ones(self) -> None:
        sources = {
            "project_validator/a.py": SOURCE,
            "project_validator/d.py": None,
            "project_validator/new.py": "def n():\n    return 1\n",
            "project_validator/top.py": SOURCE,
            "project_validator/sp ace.py": None,
        }
        reads: list[str] = []

        def read(path: str) -> str | None:
            reads.append(path)
            return sources[path]

        self.assertEqual(patterns_for(DIFF, read), ["project_validator.new.x_n*"])
        self.assertEqual(sorted(reads), sorted(sources))

    def test_only_python_files_of_the_package_count(self) -> None:
        diff = DIFF.replace("project_validator/", "tests/").replace("tests/new.py", "project_validator/new.txt")
        self.assertEqual(patterns_for(diff, lambda path: SOURCE), [])


def _run(*command: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    # The user's git configuration (signing, diff prefixes) must not reach the test's repository or the script.
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(  # noqa: S603 - tests
        command, cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace", check=False
    )


def _script(revisions: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return _run(sys.executable, str(Path(changed_mutants.__file__).resolve()), revisions, cwd=cwd)


class MainTests(unittest.TestCase):
    def test_runs_as_a_script_from_a_subdirectory_of_a_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "project_validator"
            package.mkdir()
            (package / "mod.py").write_text(SOURCE, encoding="utf-8")
            git = ("git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", tmp)
            for step in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
                self.assertEqual(_run(*git, *step).returncode, 0)
            changed = SOURCE.replace("return x + 1", "return x + 2").replace("return 1\n", "return 10\n")
            (package / "mod.py").write_text(changed, encoding="utf-8")
            done = _script("HEAD", cwd=str(package))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "project_validator.mod.x_top*\nproject_validator.mod.xǁKlassǁmethod*\n")

    def test_a_bad_revision_fails(self) -> None:
        done = _script("no-such-revision...HEAD")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")
