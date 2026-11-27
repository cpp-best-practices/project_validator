"""File formats (upstream #383, part A): the validator checks, itself, that each image, archive, database, document,
sound and text file of a format it reads is sound: whole, not truncated, and of the format its name says."""

from __future__ import annotations

import bz2
import contextlib
import gzip
import io
import lzma
import plistlib
import sqlite3
import struct
import tarfile
import unittest
import wave
import zipfile
import zlib
from unittest import mock

from project_validator.checks.data_wellformed import data_wellformed
from project_validator.core import Status
from project_validator.ecosystems import file_formats
from project_validator.ecosystems.file_formats import FILE_FORMATS, LFS_POINTER, PARSERS
from project_validator.facts.structure import SourceFile
from project_validator.parsing import ParseError
from tests.support import make_context, temp_project


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IHDR = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
PNG = PNG_SIGNATURE + IHDR + _chunk(b"IDAT", zlib.compress(b"\x00\x00")) + _chunk(b"IEND", b"")
JPEG = (
    b"\xff\xd8"
    + b"\xff\xe0"
    + struct.pack(">H", 16)
    + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xda"
    + struct.pack(">H", 8)
    + b"\x01\x01\x00\x00\x3f\x00"
    + b"\x12\x34\xff\x00\x56"
    + b"\xff\xd9"
)
GIF = (
    b"GIF89a"
    + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0)
    + b"\x00\x00\x00\xff\xff\xff"
    + b"\x2c"
    + struct.pack("<HHHHB", 0, 0, 1, 1, 0)
    + b"\x02\x02\x44\x01\x00"
    + b"\x3b"
)
_DIB = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
BMP = b"BM" + struct.pack("<IHHI", 14 + len(_DIB) + 4, 0, 0, 14 + len(_DIB)) + _DIB + b"\x00\x00\xff\x00"
ICO = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 1, 1, 0, 0, 1, 32, len(PNG), 22) + PNG
_VP8L = b"\x2f\x00\x00\x00\x00"
WEBP = (
    b"RIFF"
    + struct.pack("<I", 4 + 8 + len(_VP8L) + 1)
    + b"WEBP"
    + b"VP8L"
    + struct.pack("<I", len(_VP8L))
    + _VP8L
    + b"\x00"
)
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\nstartxref\n9\n%%EOF\n"
PEM = b"-----BEGIN CERTIFICATE-----\nTUlJQg==\n-----END CERTIFICATE-----\n"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n'


def _zip(*members: tuple[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


def _tar(*members: tuple[str, bytes], mode: str = "w") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:  # type: ignore[call-overload]
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _sqlite() -> bytes:
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("create table t (x)")
        connection.executemany("insert into t values (?)", [(i,) for i in range(200)])
        connection.commit()
        return connection.serialize()


def _wav(frames: int = 8) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _problem(path: str, data: bytes) -> str | None:
    """Why the file at `path` holding `data` is not sound, by the parser of its format; None when it is."""
    context_free = file_formats.format_of(path)
    assert context_free is not None, path  # noqa: S101 - every path here has a format
    try:
        PARSERS[context_free].parse(path, data)
    except ParseError as error:
        return error.message
    return None


SOUND = {
    "logo.png": PNG,
    "photo.jpg": JPEG,
    "photo.jpeg": JPEG,
    "anim.gif": GIF,
    "icon.bmp": BMP,
    "favicon.ico": ICO,
    "image.webp": WEBP,
    "icon.svg": SVG,
    "bundle.zip": _zip(("a.txt", b"a")),
    "lib.jar": _zip(("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\n")),
    "pkg.whl": _zip(("pkg/__init__.py", b"")),
    "source.tar": _tar(("src/a.c", b"int a;\n")),
    "source.tar.gz": _tar(("src/a.c", b"int a;\n"), mode="w:gz"),
    "source.tgz": _tar(("src/a.c", b"int a;\n"), mode="w:gz"),
    "source.tar.bz2": _tar(("src/a.c", b"int a;\n"), mode="w:bz2"),
    "source.tar.xz": _tar(("src/a.c", b"int a;\n"), mode="w:xz"),
    "log.gz": gzip.compress(b"x" * 100),
    "log.bz2": bz2.compress(b"x" * 100),
    "log.xz": lzma.compress(b"x" * 100),
    "cache.sqlite": _sqlite(),
    "cache.sqlite3": _sqlite(),
    "manual.pdf": PDF,
    "beep.wav": _wav(),
    "cert.pem": PEM,
    "Info.plist": plistlib.dumps({"CFBundleName": "app"}),
    "binary.plist": plistlib.dumps({"a": 1}, fmt=plistlib.FMT_BINARY),
    "setup.cfg": b"[metadata]\nname = app\n",
    "tox.ini": b"[tox]\nenvlist = py314\n",
    ".editorconfig": b"root = true\n\n[*]\nindent_style = space\n",
    ".gitmodules": b'[submodule "lib"]\n\tpath = lib\n\turl = https://example.org/lib.git\n',
    "table.csv": b"a,b\n1,2\n3,4\n",
    "table.tsv": b"a\tb\n1\t2\n",
}


class SoundFileTests(unittest.TestCase):
    def test_a_sound_file_of_each_format_parses(self) -> None:
        for path, data in SOUND.items():
            with self.subTest(path=path):
                self.assertIsNone(_problem(path, data))

    def test_every_format_has_a_parser_and_a_sound_example(self) -> None:
        self.assertEqual(set(PARSERS), set(FILE_FORMATS.languages))
        self.assertEqual({file_formats.format_of(path) for path in SOUND}, set(FILE_FORMATS.languages))


class UnsoundFileTests(unittest.TestCase):
    def _says(self, path: str, data: bytes, expected: str) -> None:
        problem = _problem(path, data)
        self.assertIsNotNone(problem, path)
        self.assertIn(expected, problem or "")

    def test_a_truncated_file_of_each_binary_format_does_not_parse(self) -> None:
        for path in (
            *("logo.png", "photo.jpg", "anim.gif", "icon.bmp", "favicon.ico", "image.webp", "bundle.zip"),
            *("source.tar", "source.tar.gz", "log.gz", "log.bz2", "log.xz", "cache.sqlite", "manual.pdf", "beep.wav"),
        ):
            with self.subTest(path=path):
                data = SOUND[path]
                self.assertIsNotNone(_problem(path, data[: len(data) * 2 // 3]), path)

    def test_a_git_lfs_pointer_is_not_the_file(self) -> None:
        pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 1234\n"
        self.assertTrue(pointer.startswith(LFS_POINTER))
        for path in ("logo.png", "bundle.zip", "manual.pdf", "cache.sqlite"):
            with self.subTest(path=path):
                self._says(path, pointer, "a Git LFS pointer, not the file: run git lfs pull, or check .gitattributes")

    def test_a_file_of_another_format_says_which(self) -> None:
        self._says("logo.png", JPEG, "not a PNG file: it is a JPEG file")
        self._says("photo.jpg", PNG, "not a JPEG file: it is a PNG file")
        self._says("bundle.zip", b"<!DOCTYPE html>\n<html></html>\n", "not a ZIP archive: it is an HTML page")
        self._says("logo.png", b"hello", "not a PNG file")

    def test_a_png_whose_line_endings_were_translated_says_so(self) -> None:
        self._says("logo.png", PNG.replace(b"\r\n", b"\n", 1), "its line endings were translated")
        self._says("logo.png", PNG.replace(b"\r\n", b"\r\r\n", 1), "its line endings were translated")

    def test_a_png_chunk_with_a_wrong_checksum(self) -> None:
        self._says("logo.png", PNG[:-4] + b"\x00\x00\x00\x00", "IEND chunk's checksum is wrong")
        no_header = PNG_SIGNATURE + _chunk(b"IEND", b"")
        self._says("logo.png", no_header, "IHDR is not the first chunk")
        bad_pixels = PNG_SIGNATURE + IHDR + _chunk(b"IDAT", b"not zlib") + _chunk(b"IEND", b"")
        self._says("logo.png", bad_pixels, "its image data does not decompress")
        cut_pixels = PNG_SIGNATURE + IHDR + _chunk(b"IDAT", zlib.compress(b"\x00" * 64)[:-6]) + _chunk(b"IEND", b"")
        self._says("logo.png", cut_pixels, "its image data does not decompress")
        self._says("logo.png", PNG[:-12], "truncated: IEND is not the last chunk")

    def test_image_headers_and_markers(self) -> None:
        self._says("favicon.ico", struct.pack("<HHH", 0, 5, 1) + ICO[6:], "not an ICO file")
        self._says("photo.jpg", b"\xff\xd8\x00\x00" + JPEG[2:], "no marker at byte 2")
        self.assertIsNone(_problem("photo.jpg", b"\xff\xd8\xff\x01" + JPEG[2:]))  # a marker without a segment
        exif = b"EXIF" + struct.pack("<I", 2) + b"\x00\x00"
        self._says("image.webp", b"RIFF" + struct.pack("<I", 4 + len(exif)) + b"WEBP" + exif, "no image chunk")
        fmt = b"fmt " + struct.pack("<I", 16) + bytes(16)
        self._says("beep.wav", b"RIFF" + struct.pack("<I", 4 + len(fmt)) + b"WAVE" + fmt, "no data chunk")

    def test_a_riff_file_shorter_than_it_says(self) -> None:
        longer = WEBP[:4] + struct.pack("<I", len(WEBP) + 100) + WEBP[8:]
        self._says("image.webp", longer, "truncated: it says it holds")

    def test_an_archive_member_outside_the_archive_is_a_problem(self) -> None:
        self._says("bundle.zip", _zip(("../evil.sh", b"")), "../evil.sh would be written outside the archive")
        self._says("source.tar", _tar(("/etc/passwd", b"")), "/etc/passwd would be written outside the archive")
        self._says("source.tar.gz", _tar(("../x", b""), mode="w:gz"), "../x would be written outside the archive")

    def test_an_archive_with_a_corrupted_member(self) -> None:
        data = bytearray(_zip(("a.txt", b"some text to compress " * 20)))
        data[40] ^= 0xFF
        self.assertIsNotNone(_problem("bundle.zip", bytes(data)))

    def test_a_decompression_bomb_is_read_only_so_far(self) -> None:
        bomb = gzip.compress(b"x" * (file_formats.MAX_DECOMPRESSED + 1024))
        self.assertIsNone(_problem("log.gz", bomb))
        self.assertIsNone(_problem("source.tar.gz", bomb))  # no tar archive, but read only so far

    def test_an_encrypted_member_is_not_read(self) -> None:
        """Its password is not known here (neovim's test archive of a secret.txt)."""
        data = bytearray(_zip(("secret.txt", b"opaque")))
        for header, flags in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):  # the local and central headers' flags
            at = data.index(header) + flags
            data[at] |= 0x1
        with zipfile.ZipFile(io.BytesIO(bytes(data))) as archive:
            self.assertTrue(archive.infolist()[0].flag_bits & 0x1)
        self.assertIsNone(_problem("bundle.zip", bytes(data)))

    def test_an_unknown_encoding_is_a_problem_not_a_crash(self) -> None:
        declared = b'<?xml version="1.0" encoding="UTF-9"?>\n<svg/>\n'
        self._says("icon.svg", declared, "unknown encoding")
        self._says("Info.plist", declared.replace(b"svg", b"plist"), "not a property list")

    def test_an_archive_is_read_only_so_far(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("first.txt", b"f" * 2000)
            archive.writestr("second.txt", b"SECOND")
        data = buffer.getvalue().replace(b"SECOND", b"SECONX")  # its checksum no longer holds
        self.assertIsNotNone(_problem("bundle.zip", data))
        with mock.patch.object(file_formats, "MAX_DECOMPRESSED", 1000):
            self.assertIsNone(_problem("bundle.zip", data))

    def test_a_corrupted_database_fails_its_integrity_check(self) -> None:
        data = bytearray(_sqlite())
        data[4096 + 100 : 4096 + 400] = b"\xff" * 300
        self._says("cache.sqlite", bytes(data), "integrity check")

    def test_a_pdf_without_its_trailer(self) -> None:
        self._says("manual.pdf", PDF.replace(b"%%EOF", b""), "no %%EOF trailer")
        self._says("manual.pdf", PDF.replace(b"startxref", b"xref"), "no startxref")

    def test_text_formats(self) -> None:
        self._says("cert.pem", b"-----BEGIN CERTIFICATE-----\nTUlJQg==\n", "BEGIN CERTIFICATE has no END")
        self._says("cert.pem", b"-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----\n", "not base64")
        self._says("cert.pem", b"no blocks\n", "no PEM block")
        self._says(".gitmodules", b'[submodule "lib"\n\tpath = lib\n', "line 1")
        self._says("setup.cfg", b"name = app\n", "no section header")
        self._says("Info.plist", b"<plist><dict><key>a</key></plist>", "not a property list")
        self._says("table.csv", b"a,b\n1,2,3\n", "line 2 has 3 fields, the header 2")
        self._says("table.tsv", b"a\tb\n1\n", "line 2 has 1 field, the header 2")
        self._says("icon.svg", b"<svg>", "no element found")
        self._says("table.csv", b'a,b\n"1,2\n', "not CSV")


class RealWorldTests(unittest.TestCase):
    """What the corpus showed real projects commit, and readers accept."""

    def test_bytes_after_a_pngs_end_are_ignored(self) -> None:
        self.assertIsNone(_problem("logo.png", PNG + b"\x00"))  # Documenter.jl's screenshots

    def test_an_ancillary_chunk_with_a_wrong_checksum_says_readers_skip_it(self) -> None:
        text = _chunk(b"zTXt", b"mxGraphModel\x00\x00x")[:-4] + b"\x00\x00\x00\x00"  # old draw.io exports
        problem = _problem("logo.png", PNG_SIGNATURE + IHDR + text + PNG[len(PNG_SIGNATURE + IHDR) :])
        self.assertEqual(problem, "the zTXt chunk's checksum is wrong (an ancillary chunk: readers skip it)")

    def test_an_empty_binary_file_says_so(self) -> None:
        for path, name in (("logo.jpg", "a JPEG file"), ("bundle.zip", "a ZIP archive"), ("manual.pdf", "a PDF")):
            with self.subTest(path=path):
                self.assertEqual(_problem(path, b""), f"empty, not {name}")  # hledger's logo.jpg

    def test_an_icon_named_png_says_so(self) -> None:
        self.assertEqual(_problem("favicon.png", ICO), "not a PNG file: it is an ICO file")  # cargo's

    def test_a_link_inside_the_archive_is_inside(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            link = tarfile.TarInfo("rbenv/bin/rbenv")
            link.type, link.linkname = tarfile.SYMTYPE, "../libexec/rbenv"  # pre-commit's rbenv.tar.gz
            archive.addfile(link)
            escape = tarfile.TarInfo("rbenv/escape")
            escape.type, escape.linkname = tarfile.SYMTYPE, "../../etc/passwd"
            archive.addfile(escape)
        self.assertEqual(
            _problem("source.tar", buffer.getvalue()), "../../etc/passwd would be written outside the archive"
        )

    def test_ini_keys_may_start_with_a_colon(self) -> None:
        self.assertIsNone(_problem("dist.ini", b"[Test::CheckBreaks]\n:version = 0.017\n"))  # Dist::Zilla's

    def test_a_csv_in_a_legacy_encoding_is_read_as_one(self) -> None:
        self.assertIsNone(_problem("table.csv", "nom,montant\ncaf\u00e9,3\n".encode("cp1252")))  # hledger's

    def test_a_binary_file_is_never_a_template(self) -> None:
        with temp_project({"broken.png": PNG[:-20] + b"@VERSION@", "a.py": ""}) as root:
            result = data_wellformed.run(make_context(root))
        self.assertEqual(result.status, Status.FAIL, result)


class ProjectTests(unittest.TestCase):
    def test_the_files_are_judged_by_data_wellformed(self) -> None:
        with temp_project({"logo.png": PNG, "broken.png": PNG[:20], "README.md": "x\n"}) as root:
            result = data_wellformed.run(make_context(root))
        self.assertEqual(result.status, Status.FAIL, result)
        self.assertIn("broken.png", " ".join(result.details))

    def test_binary_files_hold_no_lines_and_text_formats_do(self) -> None:
        with temp_project({"logo.png": PNG + b"\n\n\n", "table.csv": "a,b\n1,2\n", "a.py": ""}) as root:
            sources = {source.path: source for source in make_context(root).facts.of(SourceFile)}
        self.assertEqual((sources["logo.png"].language, sources["logo.png"].lines), ("PNG", 0))
        self.assertEqual((sources["table.csv"].language, sources["table.csv"].lines), ("CSV", 2))

    def test_a_fuzz_corpus_is_test_data_reported_not_judged(self) -> None:
        with temp_project({"fuzz/corpus/crash.png": PNG[:20], "a.py": ""}) as root:
            result = data_wellformed.run(make_context(root))
        self.assertNotEqual(result.status, Status.FAIL, result)
        self.assertIn("test data, not judged", " ".join(result.details))


if __name__ == "__main__":
    unittest.main()
