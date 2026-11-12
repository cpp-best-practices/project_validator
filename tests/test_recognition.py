"""How a project is recognised as ecosystems: build files by name, pattern or directory, source suffixes, content
probes and ambiguous suffixes, and the suffixes no ecosystem accounts for."""

from __future__ import annotations

import unittest
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from project_validator.build_systems.cmake.build import CMAKE
from project_validator.core import Context, Project
from project_validator.ecosystems import (
    BUILT_IN,
    C_FAMILY,
    BuildSystem,
    Ecosystem,
    RegistryError,
    claim_conflicts,
    isolated_registry,
    register,
)
from project_validator.facts.structure import SourceFile, Unit
from project_validator.project_map import ProjectStructure
from tests.support import FORMAT_ECOSYSTEM, make_context, temp_project

WIDGET = frozenset({"Widget"})


def _manifest_probe(project: Project) -> frozenset[str]:
    """A Widget project may only say so inside its manifest."""
    if project.exists("manifest.toml") and "[widget]" in project.read_head("manifest.toml"):
        return frozenset({"Widget", "Gadget"})
    return frozenset()


WIDGET_ECOSYSTEM = Ecosystem(
    label="Widget",
    languages=WIDGET,
    build_systems=(BuildSystem(name="Widget build", files=("Widgetfile", "*.widget", "*.wproj/"), languages=WIDGET),),
    source_suffixes={".wdg": "Widget"},
    ambiguous_suffixes={".wi": "Widget"},
    detect=_manifest_probe,
)


@contextmanager
def _context(files: Mapping[str, str]) -> Iterator[Context]:
    with isolated_registry():
        register(WIDGET_ECOSYSTEM)
        register(FORMAT_ECOSYSTEM)
        with temp_project(files) as root:
            yield make_context(root)


@contextmanager
def _structure(files: Mapping[str, str]) -> Iterator[ProjectStructure]:
    with _context(files) as context:
        yield context.structure


class BuildFileTests(unittest.TestCase):
    def test_build_files_are_recognised_by_name_or_pattern(self) -> None:
        for name in ("Widgetfile", "app.widget", "nested/dir/tool.widget"):
            with self.subTest(name), _structure({name: ""}) as structure:
                self.assertEqual(structure.build_systems, frozenset({"Widget build"}))
                self.assertEqual(structure.languages, WIDGET)
                self.assertEqual(structure.recognised_by, {"Widget": (f"build file {name.rsplit('/', 1)[-1]}",)})

    def test_a_pattern_must_match_the_whole_name(self) -> None:
        with _structure({"app.widget.bak": "", "Widgetfile.old": ""}) as structure:
            self.assertEqual(structure.build_systems, frozenset())

    def test_build_directories_are_recognised_by_the_files_inside_them(self) -> None:
        with _structure({"App.wproj/project.data": "", "App.wproj/settings/user.data": ""}) as structure:
            self.assertEqual(structure.build_systems, frozenset({"Widget build"}))
            self.assertEqual(structure.recognised_by, {"Widget": ("build directory App.wproj",)})
            # The build directory's own files are not reported as unrecognised.
            self.assertEqual(structure.unrecognised_suffixes, ())


class SuffixTests(unittest.TestCase):
    def test_an_ambiguous_suffix_counts_only_once_the_ecosystem_is_recognised(self) -> None:
        with _structure({"script.wi": ""}) as structure:
            self.assertEqual(structure.languages, frozenset())
            self.assertEqual(structure.unrecognised_suffixes, ((".wi", 1),))
        with _structure({"script.wi": "", "main.wdg": ""}) as structure:
            self.assertEqual(structure.languages, WIDGET)
            self.assertEqual(structure.recognised_by, {"Widget": (".wdg files", ".wi files")})
            self.assertEqual(structure.unrecognised_suffixes, ())

    def test_an_ambiguous_suffix_without_a_language_adds_none(self) -> None:
        with _structure({"CMakeLists.txt": "", "include/app.h": "", "cmake/Warnings.cmake": ""}) as structure:
            self.assertEqual(structure.languages, C_FAMILY)
            self.assertEqual(structure.recognised_by, {"C/C++": ("build file CMakeLists.txt",)})
            self.assertEqual(structure.unrecognised_suffixes, ())
        with _structure({"include/app.h": ""}) as structure:
            self.assertEqual(structure.languages, frozenset())
            self.assertEqual(structure.unrecognised_suffixes, ((".h", 1),))


class ContentProbeTests(unittest.TestCase):
    def test_a_probe_recognises_what_file_names_cannot_show(self) -> None:
        with _structure({"manifest.toml": "[widget]\nname = 'app'\n"}) as structure:
            # The probe's languages outside its ecosystem (Gadget) are ignored. The manifest is TOML, a format.
            self.assertEqual(structure.languages, WIDGET)
            self.assertEqual(structure.recognised_by, {"Data": (".toml files",), "Widget": ("content",)})

    def test_a_probe_that_finds_nothing_recognises_nothing(self) -> None:
        with _structure({"manifest.toml": "[package]\n"}) as structure:
            self.assertEqual(structure.languages, frozenset())
            self.assertEqual(structure.recognised_by, {"Data": (".toml files",)})

    def test_a_probe_reads_only_the_head_of_a_file(self) -> None:
        with temp_project({"big.txt": "a" * 10_000 + "[widget]"}) as root:
            head = Project(root).read_head("big.txt")
        self.assertEqual(len(head), 4096)
        self.assertNotIn("[widget]", head)


class UnrecognisedSuffixTests(unittest.TestCase):
    def test_suffixes_of_no_ecosystem_are_counted_most_common_first(self) -> None:
        files = {
            "src/a.odin": "",
            "src/b.odin": "",
            "tools/c.nim": "",
            "tools/d.awk": "",
            "README.md": "",
            "docs/logo.PNG": "",
            "config.h.in": "",
            "src/main.cpp~": "",
            "LICENSE": "",
            "meson.build": "project('app', 'c')\n",
        }
        with _structure(files) as structure:
            self.assertEqual(structure.unrecognised_suffixes, ((".odin", 2), (".awk", 1), (".nim", 1)))
            mapped = structure.as_dict()
        self.assertEqual(
            mapped["unrecognised_suffixes"],
            [{"suffix": ".odin", "files": 2}, {"suffix": ".awk", "files": 1}, {"suffix": ".nim", "files": 1}],
        )
        self.assertEqual(mapped["ecosystems"], {"C/C++": ["build file meson.build"]})


class ClaimConflictTests(unittest.TestCase):
    def test_built_in_ecosystems_claim_no_file_twice(self) -> None:
        self.assertEqual(claim_conflicts(BUILT_IN), [])

    def _rejected(self, **claims: object) -> str:
        ecosystem = Ecosystem(label="Widget", languages=WIDGET, **claims)  # type: ignore[arg-type]
        with isolated_registry(), self.assertRaises(RegistryError) as raised:
            register(ecosystem)
        return str(raised.exception)

    def test_an_ecosystem_must_not_claim_another_ones_build_files(self) -> None:
        cases = {
            "the same name": ("CMakeLists.txt", "build file CMakeLists.txt is already claimed by CMake"),
            "an overlapping pattern": ("CMake*.txt", "build file CMake*.txt overlaps CMakeLists.txt of CMake"),
        }
        for case, (name, expected) in cases.items():
            with self.subTest(case):
                system = BuildSystem(name="Widget build", files=(name,), languages=WIDGET)
                self.assertEqual(self._rejected(build_systems=(system,)), f"Widget: {expected}")

    def test_an_ecosystem_must_not_claim_another_ones_source_suffixes(self) -> None:
        for claims in ({"source_suffixes": {".py": "Widget"}}, {"ambiguous_suffixes": {".py": "Widget"}}):
            with self.subTest(claims=claims):
                self.assertEqual(self._rejected(**claims), "Widget: source suffix .py is already claimed by Python")

    def test_ecosystems_may_share_ambiguous_suffixes_and_build_systems(self) -> None:
        ecosystem = Ecosystem(
            label="Widget", languages=WIDGET, build_systems=(CMAKE,), ambiguous_suffixes={".h": "Widget"}
        )
        with isolated_registry():
            register(ecosystem)


class FormatRecognitionTests(unittest.TestCase):
    """A format's files are sources of the format, not of a language: they make no language the project's, they are
    read in the hidden configuration directories too (where a language's files are not: configuration is data), and
    a unit holds its formats beside its languages."""

    def test_a_formats_files_make_it_the_projects_format_not_its_language(self) -> None:
        with _structure({"src/a.wdata": "", "src/main.wdg": ""}) as structure:
            self.assertEqual((structure.languages, structure.formats), (WIDGET, frozenset({"WDATA"})))
            self.assertEqual(structure.languages_and_formats, WIDGET | {"WDATA"})
            self.assertEqual(structure.recognised_by, {"Widget": (".wdg files",), "Widget data": (".wdata files",)})
            [unit] = structure.units
            self.assertEqual((unit.languages, unit.formats), (WIDGET, frozenset({"WDATA"})))
            mapped = structure.as_dict()
        self.assertEqual((mapped["languages"], mapped["formats"]), (["Widget"], ["WDATA"]))
        self.assertEqual(
            mapped["units"],
            [{"directory": ".", "role": "product", "build_systems": [], "languages": ["Widget"], "formats": ["WDATA"]}],
        )

    def test_formats_are_read_in_the_configuration_directories_and_languages_are_not(self) -> None:
        files = {".github/settings.wdata": "", ".github/scripts/run.wdg": "", ".hidden/a.wdata": "", "README.md": ""}
        with _context(files) as context:
            self.assertEqual((context.structure.languages, context.structure.formats), (frozenset(), {"WDATA"}))
            [source] = context.facts.of(SourceFile)
            self.assertEqual(
                (source.path, source.language, source.role), (".github/settings.wdata", "WDATA", "product")
            )
            [unit] = context.facts.of(Unit)
            self.assertEqual((unit.directory, unit.languages, unit.formats), (".", frozenset(), {"WDATA"}))

    def test_vendored_data_adds_no_format(self) -> None:
        with _structure({"third_party/lib/a.wdata": "", "src/b.wdata": ""}) as structure:
            self.assertEqual(structure.formats, frozenset({"WDATA"}))
            self.assertEqual(structure.vendored, ("third_party/lib/a.wdata",))
        with _structure({"third_party/lib/a.wdata": ""}) as structure:
            self.assertEqual((structure.formats, structure.unrecognised_suffixes), (frozenset(), ()))

    def test_a_formats_suffix_is_never_unrecognised(self) -> None:
        with _structure({"a.wdata": "", "b.odin": ""}) as structure:
            self.assertEqual(structure.unrecognised_suffixes, ((".odin", 1),))
