# Documentation site

A format ecosystem of six formats, one per generator, recognised by content: MkDocs (`mkdocs.yml`), Sphinx (a
`conf.py` that sets Sphinx up), Docusaurus (`docusaurus.config.js`, `.ts`, `.mjs`, `.cjs`), mdBook (`book.toml`), Hugo
(`hugo.toml`, `.yaml`, `.json`) and Jekyll (a `_config.yml` beside `_posts/`, `_layouts/` or `_includes/`, or that
names its theme). Prose itself, the Markdown in every repository, makes no documentation site. The site's
configuration is YAML, TOML, Python or JavaScript, judged by its own profile as well.

A CI job works with the ecosystem when it runs a generator (`mkdocs`, `sphinx-build`, `docusaurus`, `mdbook`, `hugo`,
`jekyll`), a prose linter, or one of the `actions-hugo`, `actions-mdbook`, `mkdocs-deploy-gh-pages`,
`jekyll-build-pages`, `sphinx-notes/pages`, `markdownlint-cli2-action` or `vale-action` actions.

## `tests-run`

CI builds the site: `mkdocs build` (or `mkdocs gh-deploy`, `mhausenblas/mkdocs-deploy-gh-pages`), `sphinx-build`
(or `python -m sphinx`, `sphinx-notes/pages`), `docusaurus build` (through `npm run build`), `mdbook build` or
`mdbook test`, `hugo` or `hugo build`, `jekyll build` (through `bundle exec`, or `actions/jekyll-build-pages`). The
generator's configuration file is what defines the site.

## `warnings-as-errors`

The build fails on a warning: `mkdocs build --strict`, `sphinx-build -W` (`--fail-on-warning`), `onBrokenLinks:
'throw'` in `docusaurus.config`, `hugo --panicOnWarning`, `jekyll build --strict_front_matter`. mdBook has no such
switch, so the check does not apply to it.

## `static-analysis`

The prose is linted: markdownlint (`markdownlint-cli2`, or `DavidAnson/markdownlint-cli2-action`; settings in
`.markdownlint.yaml`, `.markdownlint.json` or `.markdownlint-cli2.*`) or vale (`vale`, or `errata-ai/vale-action`;
`.vale.ini`, which it needs).

## `vcs-ignore`

The built site is ignored: `site/` (MkDocs), `_build/` (Sphinx), `build/` and `.docusaurus/` (Docusaurus), `book/`
(mdBook), `public/` (Hugo), `_site/` and `.jekyll-cache/` (Jekyll).

## `committed-artifacts`

A built site is a build output, never committed.

## Not judged

Link checking (lychee, `sphinx-build -b linkcheck`, markdown-link-check) is a check of its own, not yet built.
`compiler-warnings` is a compiled language's; the prose linters are `static-analysis`. The other checks have no tool
for a site and are skipped.
