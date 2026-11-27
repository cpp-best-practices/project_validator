# File formats

Learn more: [PNG](https://www.w3.org/TR/png-3/), [JPEG](https://jpeg.org/jpeg/),
[GIF](https://www.w3.org/Graphics/GIF/spec-gif89a.txt), [BMP](https://en.wikipedia.org/wiki/BMP_file_format),
[ICO](https://en.wikipedia.org/wiki/ICO_(file_format)), [WebP](https://developers.google.com/speed/webp),
[SVG](https://www.w3.org/Graphics/SVG/), [ZIP archive](https://en.wikipedia.org/wiki/ZIP_(file_format)), [tar
archive](https://www.gnu.org/software/tar/manual/html_node/Standard.html), [gzip](https://www.gzip.org/),
[bzip2](https://sourceware.org/bzip2/), [xz](https://tukaani.org/xz/), [SQLite
database](https://www.sqlite.org/fileformat.html), [PDF](https://en.wikipedia.org/wiki/PDF),
[WAV](https://en.wikipedia.org/wiki/WAV), [INI](https://en.wikipedia.org/wiki/INI_file),
[CSV](https://www.rfc-editor.org/rfc/rfc4180),
[TSV](https://www.iana.org/assignments/media-types/text/tab-separated-values),
[PEM](https://www.rfc-editor.org/rfc/rfc7468), [Property list](https://en.wikipedia.org/wiki/Property_list).

The files a project commits beside its code that are not programs: images (PNG `.png`, JPEG `.jpg` `.jpeg`, GIF `.gif`,
BMP `.bmp`, ICO `.ico`, WebP `.webp`, SVG `.svg`), archives (ZIP `.zip` and the formats built on it: `.jar`, `.war`,
`.ear`, `.aar`, `.whl`, `.nupkg`, `.vsix`, `.epub`, `.docx`, `.xlsx`, `.pptx`, `.odt`, `.ods`, `.odp`; tar `.tar`
`.tgz`; gzip `.gz`, bzip2 `.bz2`, xz `.xz`, and `.tar.gz`, `.tar.bz2`, `.tar.xz`), SQLite databases (`.sqlite`,
`.sqlite3`, `.db3`), PDF (`.pdf`), WAV (`.wav`), and a few text formats: INI (`.ini`, `setup.cfg`, `.editorconfig`,
`.gitmodules`), CSV (`.csv`), TSV (`.tsv`), PEM (`.pem`) and property lists (`.plist`, XML or binary). A format, not a
language, as [Data](data.md) is: none of the checks of code applies, and its files make no language the project's.
An image or an archive holds no lines, so its size never weighs a language's share of the code in the score.

## `data-wellformed`

The validator reads each file itself, with Python's standard library only (upstream #383, part A), and fails one that
is not sound:

- **Images:** the format's signature; a PNG's chunk checksums, IHDR first and IEND last, and its image data
  decompresses; a JPEG's marker segments and its end of image; a GIF's blocks up to its trailer; the sizes a BMP, an
  ICO or a WebP declares fit in the file; an SVG parses as XML (its external entities never read).
- **Archives:** every ZIP member decompresses with its checksum right; a tar archive's members fit in it; a gzip,
  bzip2 or xz stream decompresses to its end. A member that would be written outside the archive (`../`, an absolute
  path, a link pointing out) is a problem too.
- **Databases and documents:** an SQLite database passes `PRAGMA integrity_check`, read in memory; a PDF has its
  `%PDF-` header and its `startxref` and `%%EOF` trailer; a WAV file's RIFF chunks fit and it has its `fmt` and `data`
  chunks.
- **Text formats:** INI has its section headers (an `.editorconfig`'s preamble apart); each CSV or TSV record has as
  many fields as the header; each PEM block has its END and a base64 body; a property list loads.

A file that is not what its name says says what it is instead: **a Git LFS pointer committed in place of the file**
(run `git lfs pull`, or check `.gitattributes`), an HTML error page saved as an archive, a JPEG named `.png`, or a PNG
whose line endings a `.gitattributes` text setting translated (its signature holds `\r\n` so that this shows).

Decompression stops at 64 MiB: what was read up to there is taken as sound, so a decompression bomb costs nothing. As
for every format, files over 5 MiB are not read (`large-files` asks for those to be in Git LFS), and a test suite's
files (`tests/`, fixtures, a fuzz corpus) are read but only reported: a fuzzer's seeds are malformed on purpose.

`file-soundness` is the other side of this: whether CI runs a tool (ClamAV, magick, qpdf, ...) over these files.
