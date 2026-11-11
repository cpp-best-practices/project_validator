# Clojure

Recognised by `.clj`, `.cljs` and `.cljc` sources and by the build files: `deps.edn` (the Clojure CLI), `project.clj`
(Leiningen), `bb.edn` (Babashka) and `shadow-cljs.edn`; once the project is known to be Clojure, Babashka `.bb`
scripts are Clojure too, and EDN data files belong to the ecosystem with no language of their own. `.cpcache`,
`target` beside a build file and `.shadow-cljs` are build trees.

The Clojure CLI runs aliases (`clojure -M:test`, `-X:test`, `-T:build test`): a tool is known by its alias's name
when CI runs it that way (`:test`, `:kaocha`, `:cloverage`, `:cljfmt`, `:nvd`), and by its program when run directly.

## `tests-run`

`deftest` (clojure.test), `defspec` or speclj `describe` under `test/` or `spec/` (or `*_test.clj`, `*_spec.clj`),
run by `clojure -M:test` (an alias named for the tests, kaocha or coverage), `lein test`, `lein kaocha`, `kaocha`,
`bb test`, or `shadow-cljs compile test`.

## `coverage`

cloverage counts the forms (and lines) the tests run, the finest Clojure has: `lein cloverage`, or the CLI alias
that runs it (`clojure -M:coverage`).

## `platform-matrix`

Clojure runs on the JDK: the toolchains are the JDK versions the JVM profile recognises (`actions/setup-java`'s
`java-version`, a `temurin:` image); the Clojure version is the dependency `deps.edn` names, not a CI toolchain.

## `compiler-warnings`

clj-kondo's lints stand in for compiler warnings: `clj-kondo --lint src test` (or `lein clj-kondo`, `clojure
-M:clj-kondo`) runs in CI, and `*warn-on-reflection*` is set (`:global-vars` in `project.clj`, or
`(set! *warn-on-reflection* true)` in the namespaces), the one warning the compiler has. Installing clj-kondo
(setup-clojure's `clj-kondo:` input) is not running it.

## `warnings-as-errors`

clj-kondo exits non-zero on a warning by default; `--fail-level error` turns that off, so a run without it counts.

## `code-formatting`

cljfmt (`cljfmt check` fails, `cljfmt fix` rewrites; `lein cljfmt check`, `clojure -M:cljfmt check`), cljstyle
(`check`/`fix`) or zprint (`--check`/`--write`); each has a default style, with `.cljfmt.edn`, `.cljstyle` or
`.zprintrc` picking another.

## `static-analysis`

clj-kondo, with the linters `.clj-kondo/config.edn` sets (its defaults without).

## `security-scanning`

semgrep, which reads Clojure; CodeQL and GitLab SAST do not.

## `dependency-audit`

nvd-clojure (`clojure -M:nvd`, `lein nvd check`) or clj-watson.

## `committed-artifacts`

`.cpcache/` (the CLI), `target/` (Leiningen and tools.build), `.shadow-cljs/`, and the REPL's `.nrepl-port`.

## `vcs-ignore`

The same, each of those the project's build systems write; `.nrepl-port` for every project.

## Not judged

Clojure is dynamically typed (`type-checking`); lizard does not parse it (`function-limits`); `deps.edn` and
`project.clj` pin every version and have no lock file (`dependency-management`); no fuzzer or mutation testing tool
the validator knows runs Clojure tests; the JVM builds no debug or release configuration (`ci-build-types`,
`hardening`, `cxx-extensions`).
