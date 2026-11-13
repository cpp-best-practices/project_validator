# LaTeX

Recognised by a document: a `.tex` that declares its class (`\documentclass`), or a `.latexmkrc`. The sources
(`.tex`, `.sty`, `.cls`, `.dtx`, `.ltx`; `.bib` beside them) count once a document is found, so a stray `.tex`
fragment makes no LaTeX project. A CI job uses LaTeX when it runs latexmk, a TeX engine, chktex, latexindent, bibtex
or biber, or installs TeX Live with `xu-cheng/latex-action` or `TeX-Live/setup-texlive-action`.

## `tests-run`

CI compiles the documents: `latexmk`, `pdflatex`, `xelatex`, `lualatex` or `tectonic`, or `xu-cheng/latex-action`
(its `root_file`). The documents themselves are what defines the tests.

## `compiler-warnings`

LaTeX has none; chktex (or lacheck) stands in, run over the documents in CI, with its settings in `.chktexrc`.

## `static-analysis`

chktex or lacheck.

## `code-formatting`

`latexindent --check` (`-k`), which fails on a file it would change; `latexindent -w` rewrites. Its settings are in
`latexindent.yaml` or `localSettings.yaml`, with a default style without them.

## `vcs-ignore`

What compiling leaves is ignored: the compiler's auxiliary files (`*.aux`, `*.log`, `*.out`, `*.toc`), latexmk's
records (`*.fls`, `*.fdb_latexmk`) and SyncTeX data (`*.synctex.gz`).

## `committed-artifacts`

Auxiliary files, latexmk's records and SyncTeX data are build outputs, never committed. The built PDF is not asked
for: a project may commit its figures as PDFs.

## Not judged

`warnings-as-errors` has no switch (chktex reports, the engine goes on); `platform-matrix` would count TeX Live
versions, which a document rarely builds several of; `coverage` has no meaning for a document. The other checks have
no tool for LaTeX and are skipped.
