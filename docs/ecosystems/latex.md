# LaTeX

Learn more: [LaTeX](https://www.latex-project.org/).

Recognised by a document: a `.tex` that declares its class (`\documentclass`), a `.latexmkrc`, or l3build's
`build.lua` naming its `module` (a LaTeX package). The sources (`.tex`, `.sty`, `.cls`, `.dtx`, `.ltx`; `.bib` beside
them; l3build's `.lvt` and `.pvt` tests and their `.tlg` logs) count once one is found, so a stray `.tex` fragment makes
no LaTeX project. A CI job uses LaTeX when it runs latexmk, a TeX engine, chktex, latexindent, bibtex, biber or
l3build, or installs TeX Live with `xu-cheng/latex-action` or `TeX-Live/setup-texlive-action`.

## `tests-run`

CI compiles the documents: `latexmk`, `pdflatex`, `xelatex`, `lualatex` or `tectonic`, or `xu-cheng/latex-action`
(its `root_file`). The documents themselves are what defines the tests. A package's regression tests are l3build's
`.lvt` and `.pvt` files, which `l3build check` (or `texlua l3build.lua check`) runs, failing when a log differs from
its `.tlg`. l3build runs them in LuaTeX, so they test the Lua the package loads as well (l3build's own
`l3build-*.lua`, upstream #276).

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
