"""File formats (upstream #383, part A): the images, archives, databases, documents, sounds and the few text formats
(INI, CSV, PEM, property lists, SVG) a project commits beside its code. A format, not a language: the validator reads
each file itself, with the standard library only, for `data-wellformed`: it is whole (not truncated), its checksums
and declared sizes hold, and it is the format its name says. A Git LFS pointer committed in place of the file, an
HTML error page saved as an archive and a PNG whose line endings a `.gitattributes` text setting translated each say
so. An archive's members that would be written outside it (`../`, an absolute path) are a problem too.

Decompression is bounded (`MAX_DECOMPRESSED`): past it, what was read is taken as sound, so that a decompression bomb
costs nothing. A binary file holds no lines (`Ecosystem.lines`): its size never weighs a language's share of the code.
A fuzz corpus or a test fixture is test data, reported and not judged, as for every format.
"""

from __future__ import annotations

import base64
import binascii
import bz2
import configparser
import csv
import gzip
import io
import lzma
import plistlib
import posixpath
import re
import sqlite3
import struct
import tarfile
import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping
from pathlib import PurePosixPath

from project_validator.ecosystems.data import parse_xml
from project_validator.ecosystems.model import Ecosystem
from project_validator.facts.wellformed import ParseError, Parser, decoded

PNG, JPEG, GIF, BMP, ICO, WEBP, SVG = "PNG", "JPEG", "GIF", "BMP", "ICO", "WebP", "SVG"
ZIP, TAR, GZIP, BZIP2, XZ = "ZIP archive", "tar archive", "gzip", "bzip2", "xz"
SQLITE, PDF, WAV = "SQLite database", "PDF", "WAV"
INI, CSV, TSV, PEM, PLIST = "INI", "CSV", "TSV", "PEM", "Property list"
BINARY = frozenset({PNG, JPEG, GIF, BMP, ICO, WEBP, ZIP, TAR, GZIP, BZIP2, XZ, SQLITE, PDF, WAV})

# How much an archive or a compressed stream is decompressed to check it: past this, what was read is taken as sound.
MAX_DECOMPRESSED = 64 * 1024 * 1024
_STEP = 1024 * 1024

# What a Git LFS pointer starts with (https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md).
LFS_POINTER = b"version https://git-lfs.github.com/spec/"
# What each binary format starts with, and what it is called: to say what a file is when it is not what its name says.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG", "a PNG file"),
    (b"\x00\x00\x01\x00", "an ICO file"),
    (b"\xff\xd8\xff", "a JPEG file"),
    (b"GIF8", "a GIF file"),
    (b"PK\x03\x04", "a ZIP archive"),
    (b"\x1f\x8b", "a gzip stream"),
    (b"BZh", "a bzip2 stream"),
    (b"\xfd7zXZ\x00", "an xz stream"),
    (b"SQLite format 3\x00", "an SQLite database"),
    (b"%PDF-", "a PDF"),
    (b"RIFF", "a RIFF file (WAV, WebP)"),
)
_HTML = re.compile(rb"^\s*<(?:!doctype\s+html|html)\b", re.IGNORECASE)


def _not(name: str, data: bytes) -> ParseError:
    """Why `data` is not the `name` (`a PNG file`) its suffix says: what it is instead, when that can be told."""
    if not data:
        return ParseError(f"empty, not {name}")
    if data.startswith(LFS_POINTER):
        return ParseError("a Git LFS pointer, not the file: run git lfs pull, or check .gitattributes")
    what = next((found for magic, found in _MAGIC if data.startswith(magic) and found != name), None)
    if what is None and _HTML.match(data[:256]):
        what = "an HTML page"
    if what is not None:
        return ParseError(f"not {name}: it is {what}")
    return ParseError(f"not {name}: its header is not one")


def _expect(data: bytes, magic: bytes, name: str) -> None:
    if not data.startswith(magic):
        raise _not(name, data)


def _unpack(layout: str, data: bytes, at: int, what: str) -> tuple[int, ...]:
    """The fields `layout` reads from `data` at `at`; `ParseError` that the file is truncated in `what` when it is
    too short."""
    end = at + struct.calcsize(layout)
    if end > len(data):
        raise ParseError(f"truncated in {what}")
    return struct.unpack_from(layout, data, at)


# --- images


def _png_chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    at = 8
    while at < len(data):
        (length,) = _unpack(">I", data, at, "a chunk's length")
        kind, body = data[at + 4 : at + 8], data[at + 8 : at + 8 + length]
        (crc,) = _unpack(">I", data, at + 8 + length, f"the {kind.decode('latin-1')} chunk")
        if zlib.crc32(kind + body) != crc:
            skipped = " (an ancillary chunk: readers skip it)" if kind[:1].islower() else ""
            raise ParseError(f"the {kind.decode('latin-1')} chunk's checksum is wrong{skipped}")
        yield kind, body
        if kind == b"IEND":
            return  # what follows it (a stray byte some tools append) is no part of the image
        at += 12 + length


def _parse_png(_path: str, data: bytes) -> None:
    if data.startswith((b"\x89PNG\n", b"\x89PNG\r\r\n", b"\x89PNG\r\x1a")):
        raise ParseError("its line endings were translated (a .gitattributes text setting?): it is no longer a PNG")
    _expect(data, b"\x89PNG\r\n\x1a\n", "a PNG file")
    chunks = list(_png_chunks(data))
    kinds = [kind for kind, _ in chunks]
    if not kinds or kinds[0] != b"IHDR":
        raise ParseError("IHDR is not the first chunk")
    if kinds[-1] != b"IEND":
        raise ParseError("truncated: IEND is not the last chunk")
    pixels = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not _inflates(pixels):
        raise ParseError("its image data does not decompress")


def _segments(data: bytes) -> int:
    """Where a JPEG's scan starts, its marker segments read up to it."""
    at = 2
    while True:
        marker, kind = _unpack(">BB", data, at, "a marker")
        if marker != 0xFF:
            raise ParseError(f"no marker at byte {at}")
        if kind in (0x01, *range(0xD0, 0xD8)):
            at += 2
            continue
        (length,) = _unpack(">H", data, at + 2, "a marker segment")
        if at + 2 + length > len(data):
            raise ParseError("truncated in a marker segment")
        if kind == 0xDA:
            return at + 2 + length
        at += 2 + length


def _parse_jpeg(_path: str, data: bytes) -> None:
    _expect(data, b"\xff\xd8", "a JPEG file")
    if data.find(b"\xff\xd9", _segments(data)) < 0:
        raise ParseError("truncated: no end of image")


def _sub_blocks(data: bytes, at: int) -> int:
    """Where a GIF's data sub-blocks starting at `at` end."""
    while True:
        (size,) = _unpack("B", data, at, "a data block")
        at += 1 + size
        if size == 0:
            return at


def _colour_table(flags: int) -> int:
    return 3 * (2 << (flags & 7)) if flags & 0x80 else 0


def _parse_gif(_path: str, data: bytes) -> None:
    if not data.startswith((b"GIF87a", b"GIF89a")):
        raise _not("a GIF file", data)
    (flags,) = _unpack("B", data, 10, "the screen descriptor")
    at = 13 + _colour_table(flags)
    while True:
        (block,) = _unpack("B", data, at, "the blocks before the trailer")
        if block == 0x3B:
            return
        if block == 0x2C:
            (image_flags,) = _unpack("B", data, at + 9, "an image descriptor")
            at = _sub_blocks(data, at + 10 + _colour_table(image_flags) + 1)
        elif block == 0x21:
            at = _sub_blocks(data, at + 2)
        else:
            raise ParseError(f"an unknown block at byte {at}")


def _parse_bmp(_path: str, data: bytes) -> None:
    _expect(data, b"BM", "a BMP file")
    size, _, _, pixels = _unpack("<IHHI", data, 2, "the file header")
    if size > len(data) or pixels >= len(data):
        raise ParseError(f"truncated: it says it holds {size:,} bytes, and holds {len(data):,}")


def _parse_ico(_path: str, data: bytes) -> None:
    reserved, kind, count = _unpack("<HHH", data, 0, "the header")
    if reserved != 0 or kind not in (1, 2) or count == 0:
        raise _not("an ICO file", data)
    for entry in range(count):
        *_, size, offset = _unpack("<BBBBHHII", data, 6 + 16 * entry, "the image directory")
        if offset + size > len(data):
            raise ParseError(f"truncated: image {entry + 1} ends past the end of the file")


def _riff(data: bytes, form: bytes, name: str) -> dict[bytes, bytes]:
    """A RIFF file's chunks (the first of each kind), checked to fit within it."""
    if not data.startswith(b"RIFF") or data[8:12] != form:
        raise _not(name, data)
    (size,) = _unpack("<I", data, 4, "the RIFF header")
    if size + 8 > len(data):
        raise ParseError(f"truncated: it says it holds {size + 8:,} bytes, and holds {len(data):,}")
    chunks: dict[bytes, bytes] = {}
    at = 12
    while at + 8 <= size + 8:
        kind, (length,) = data[at : at + 4], _unpack("<I", data, at + 4, "a chunk")
        if at + 8 + length > len(data):
            raise ParseError(f"truncated in the {kind.decode('latin-1').strip()} chunk")
        chunks.setdefault(kind, data[at + 8 : at + 8 + length])
        at += 8 + length + (length & 1)
    return chunks


def _parse_webp(_path: str, data: bytes) -> None:
    if not {b"VP8 ", b"VP8L", b"VP8X"} & set(_riff(data, b"WEBP", "a WebP file")):
        raise ParseError("no image chunk (VP8, VP8L or VP8X)")


def _parse_wav(_path: str, data: bytes) -> None:
    chunks = _riff(data, b"WAVE", "a WAV file")
    missing = [name for name in (b"fmt ", b"data") if name not in chunks]
    if missing:
        raise ParseError(f"no {missing[0].decode().strip()} chunk")


# --- archives and compressed streams


def _inflates(data: bytes) -> bool:
    """Whether `data`, a zlib stream (a PNG's image data), decompresses whole, or as far as `MAX_DECOMPRESSED`."""
    decompressor, read = zlib.decompressobj(), 0
    try:
        while data and read <= MAX_DECOMPRESSED:
            read += len(decompressor.decompress(data, _STEP))
            data = decompressor.unconsumed_tail
    except zlib.error:
        return False
    return decompressor.eof or read > MAX_DECOMPRESSED


_READERS: Mapping[str, Callable[[io.BytesIO], io.BufferedIOBase]] = {
    GZIP: lambda stream: gzip.GzipFile(fileobj=stream),
    BZIP2: bz2.BZ2File,
    XZ: lzma.LZMAFile,
}


def _decompressed(data: bytes, kind: str) -> bytes | None:
    """`data`, a `kind` stream (or several), decompressed; None when it holds more than `MAX_DECOMPRESSED`, and
    `ParseError` when it is truncated or corrupt."""
    try:
        with _READERS[kind](io.BytesIO(data)) as reader:
            out = reader.read(MAX_DECOMPRESSED + 1)
    except (EOFError, OSError, zlib.error, lzma.LZMAError) as error:
        raise ParseError(f"truncated or corrupt: the {kind} stream does not decompress ({error})") from error
    return None if len(out) > MAX_DECOMPRESSED else out


def _outside(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return path.is_absolute() or ".." in path.parts or bool(re.match(r"^[A-Za-z]:", name))


def _members_inside(names: Iterator[str]) -> None:
    for name in names:
        if _outside(name):
            raise ParseError(f"{name} would be written outside the archive")


def _parse_zip(_path: str, data: bytes) -> None:
    if not data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        raise _not("a ZIP archive", data)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _members_inside(info.filename for info in archive.infolist())
            read = 0
            for info in archive.infolist():
                if info.flag_bits & 0x1:
                    continue  # encrypted: its password is not known here
                with archive.open(info) as member:
                    while chunk := member.read(_STEP):
                        read += len(chunk)
                        if read > MAX_DECOMPRESSED:
                            return
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, OSError, ValueError, struct.error) as error:
        raise ParseError(f"a broken ZIP archive: {error}") from error


def _parse_tar_bytes(data: bytes) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            members = archive.getmembers()
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ParseError(f"a broken tar archive: {error}") from error
    if len(data) % 512 or any(member.offset_data + member.size > len(data) for member in members):
        raise ParseError("truncated: the archive ends inside a member, or not on a 512-byte block")
    _members_inside(member.name for member in members)
    for member in members:
        # A symbolic link points from its own directory (bin/rbenv -> ../libexec/rbenv stays inside), a hard link
        # from the archive's root.
        target = posixpath.join(posixpath.dirname(member.name), member.linkname) if member.issym() else member.linkname
        if (member.issym() or member.islnk()) and _outside(posixpath.normpath(target)):
            raise ParseError(f"{member.linkname} would be written outside the archive")
    if not members and data.strip(b"\x00"):
        raise ParseError("a broken tar archive: no member could be read")


def _compressed(kind: str, magic: bytes) -> Callable[[str, bytes], None]:
    """The parser of a compressed stream of `kind`: it decompresses whole, and a `.tar.<suffix>` (`.tgz`) holds a tar
    archive that parses."""

    def parse(path: str, data: bytes) -> None:
        _expect(data, magic, f"a {kind} stream" if kind != XZ else "an xz stream")
        inner = _decompressed(data, kind)
        if inner is not None and _tarred(path):
            _parse_tar_bytes(inner)

    return parse


def _tarred(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name.endswith((".tgz", ".tbz2", ".txz")) or ".tar." in name


def _parse_tar(path: str, data: bytes) -> None:
    if PurePosixPath(path).suffix.lower() == ".tgz":
        _compressed(GZIP, b"\x1f\x8b")(path, data)
        return
    if len(data) < 512 or (data[257:262] != b"ustar" and data.startswith(tuple(magic for magic, _ in _MAGIC))):
        raise _not("a tar archive", data)
    _parse_tar_bytes(data)


# --- databases and documents


def _parse_sqlite(_path: str, data: bytes) -> None:
    _expect(data, b"SQLite format 3\x00", "an SQLite database")
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(data)
        problems = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    except sqlite3.DatabaseError as error:
        raise ParseError(f"its integrity check fails: {error}") from error
    finally:
        connection.close()
    if problems != ["ok"]:
        raise ParseError(f"its integrity check fails: {problems[0]}")


def _parse_pdf(_path: str, data: bytes) -> None:
    if b"%PDF-" not in data[:1024]:
        raise _not("a PDF", data)
    tail = data[-2048:]
    if b"%%EOF" not in tail:
        raise ParseError("truncated: no %%EOF trailer")
    if b"startxref" not in tail:
        raise ParseError("no startxref before its %%EOF")


# --- text formats


# The INI files whose readers ask for a section before any setting; the others (an .editorconfig's `root = true`,
# Vale's `StylesPath`) may have settings before their first section.
_SECTIONED = frozenset({"setup.cfg", "tox.ini", ".gitmodules"})


def _ini_parser(delimiters: tuple[str, ...] = ("=", ":")) -> configparser.RawConfigParser:
    return configparser.RawConfigParser(strict=False, interpolation=None, allow_no_value=True, delimiters=delimiters)


def _read_ini(text: str, path: str) -> None:
    """Read `text` with `=` or `:` between a key and its value; failing that, with `=` alone, as readers that allow a
    `:` in a key do (Dist::Zilla's `:version = 0.017`)."""
    try:
        _ini_parser().read_string(text, source=path)
    except configparser.ParsingError:
        _ini_parser(("=",)).read_string(text, source=path)


def _parse_ini(path: str, data: bytes) -> None:
    text = decoded(data)
    if PurePosixPath(path).name not in _SECTIONED:
        text = "[preamble]\n" + text
    try:
        _read_ini(text, path)
    except configparser.MissingSectionHeaderError as error:
        raise ParseError(f"line {error.lineno}: no section header before its first setting", error.lineno) from error
    except configparser.ParsingError as error:
        line = error.errors[0][0] - (PurePosixPath(path).name not in _SECTIONED)
        raise ParseError(f"not INI at line {line}", line) from error


def _delimited(delimiter: str) -> Callable[[str, bytes], None]:
    """The parser of CSV (or TSV, with `delimiter`): as many fields in each record as in the header. It is read as
    UTF-8, or, when it is not, as Latin-1: a table may be in a legacy encoding (cp1252, ISO 8859-1), which bytes alone
    can not tell."""

    def parse(_path: str, data: bytes) -> None:
        try:
            text = decoded(data)
        except ParseError:
            text = data.decode("latin-1")
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            header = next(rows, None)
            for row in rows:
                if row and len(row) != len(header or ()):
                    fields = f"{len(row)} field{'s' * (len(row) != 1)}"
                    raise ParseError(
                        f"line {rows.line_num} has {fields}, the header {len(header or ())}", rows.line_num
                    )
        except csv.Error as error:
            raise ParseError(f"not CSV at line {rows.line_num}: {error}", rows.line_num) from error

    return parse


_PEM = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----\n?(.*?)(?:-----END \1-----|\Z)", re.DOTALL)


def _parse_pem(_path: str, data: bytes) -> None:
    text = decoded(data)
    blocks = list(_PEM.finditer(text))
    if not blocks:
        raise ParseError("no PEM block (-----BEGIN ...-----)")
    for block in blocks:
        if not block[0].rstrip().endswith("-----") or "-----END" not in block[0]:
            raise ParseError(f"BEGIN {block[1]} has no END")
        body = "".join(line for line in block[2].splitlines() if ":" not in line)  # headers (Proc-Type: ...) apart
        try:
            base64.b64decode(body, validate=True)
        except binascii.Error as error:
            raise ParseError(f"the {block[1]} block is not base64") from error


def _parse_plist(_path: str, data: bytes) -> None:
    try:
        plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError) as error:
        raise ParseError(f"not a property list: {error}") from error
    except Exception as error:
        raise ParseError(f"not a property list: {error}") from error


PARSERS: Mapping[str, Parser] = {
    name: Parser(format=name, parse=parse, binary=name in BINARY)
    for name, parse in {
        PNG: _parse_png,
        JPEG: _parse_jpeg,
        GIF: _parse_gif,
        BMP: _parse_bmp,
        ICO: _parse_ico,
        WEBP: _parse_webp,
        SVG: parse_xml,
        ZIP: _parse_zip,
        TAR: _parse_tar,
        GZIP: _compressed(GZIP, b"\x1f\x8b"),
        BZIP2: _compressed(BZIP2, b"BZh"),
        XZ: _compressed(XZ, b"\xfd7zXZ\x00"),
        SQLITE: _parse_sqlite,
        PDF: _parse_pdf,
        WAV: _parse_wav,
        INI: _parse_ini,
        CSV: _delimited(","),
        TSV: _delimited("\t"),
        PEM: _parse_pem,
        PLIST: _parse_plist,
    }.items()
}

# The parsers, as components are found (see `project_validator.components.known`).
FILE_FORMAT_PARSERS = tuple(PARSERS.values())

_SUFFIXES = {
    ".png": PNG,
    ".jpg": JPEG,
    ".jpeg": JPEG,
    ".gif": GIF,
    ".bmp": BMP,
    ".ico": ICO,
    ".webp": WEBP,
    ".svg": SVG,
    **dict.fromkeys((".zip", ".jar", ".war", ".ear", ".aar", ".whl", ".nupkg", ".vsix", ".epub"), ZIP),
    **dict.fromkeys((".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"), ZIP),
    **dict.fromkeys((".tar", ".tgz"), TAR),
    ".gz": GZIP,
    ".bz2": BZIP2,
    ".xz": XZ,
    **dict.fromkeys((".sqlite", ".sqlite3", ".db3"), SQLITE),
    ".pdf": PDF,
    ".wav": WAV,
    ".ini": INI,
    ".csv": CSV,
    ".tsv": TSV,
    ".pem": PEM,
    ".plist": PLIST,
}
_NAMES = {".editorconfig": INI, ".gitmodules": INI, "setup.cfg": INI}


def format_of(path: str) -> str | None:
    """The format the file at `path` is in, by its name; None when it is in none of these."""
    name = PurePosixPath(path).name
    return _NAMES.get(name) or _SUFFIXES.get(PurePosixPath(name.lower()).suffix)


FILE_FORMATS = Ecosystem(
    label="File formats",
    links={
        PNG: "https://www.w3.org/TR/png-3/",
        JPEG: "https://jpeg.org/jpeg/",
        GIF: "https://www.w3.org/Graphics/GIF/spec-gif89a.txt",
        BMP: "https://en.wikipedia.org/wiki/BMP_file_format",
        ICO: "https://en.wikipedia.org/wiki/ICO_(file_format)",
        WEBP: "https://developers.google.com/speed/webp",
        SVG: "https://www.w3.org/Graphics/SVG/",
        ZIP: "https://en.wikipedia.org/wiki/ZIP_(file_format)",
        TAR: "https://www.gnu.org/software/tar/manual/html_node/Standard.html",
        GZIP: "https://www.gzip.org/",
        BZIP2: "https://sourceware.org/bzip2/",
        XZ: "https://tukaani.org/xz/",
        SQLITE: "https://www.sqlite.org/fileformat.html",
        PDF: "https://en.wikipedia.org/wiki/PDF",
        WAV: "https://en.wikipedia.org/wiki/WAV",
        INI: "https://en.wikipedia.org/wiki/INI_file",
        CSV: "https://www.rfc-editor.org/rfc/rfc4180",
        TSV: "https://www.iana.org/assignments/media-types/text/tab-separated-values",
        PEM: "https://www.rfc-editor.org/rfc/rfc7468",
        PLIST: "https://en.wikipedia.org/wiki/Property_list",
    },
    kind="format",
    languages=frozenset(PARSERS),
    source_suffixes=_SUFFIXES,
    source_names=_NAMES,
    unlined=BINARY,
    incidental=True,
)
