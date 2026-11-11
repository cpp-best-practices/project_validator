# Common Lisp

Recognised by `.lisp` sources and by ASDF system definitions (`*.asd`), the build system; once the project is known to
be Common Lisp, `.cl` (OpenCL's suffix too), `.lsp` and Roswell `.ros` scripts are Lisp as well. Qlot's `.qlot/` is a
build tree.

Lisp code CI runs on a command line (`sbcl --non-interactive --eval "(asdf:test-system :shop)"`, `ros run --eval …`) is
read as the words of the command; 40ants/run-tests stands for the code it is given (`run-tests`) or its
`asdf-system`'s `test-op`, under sb-cover when it is given a `coveralls-token`.

## `tests-run`

FiveAM, Parachute, Rove or Prove tests in the test system's files (`tests/*.lisp`, `t/`, `*-tests.lisp`), run by the
system's `test-op` (`asdf:test-system`), a framework's runner called from Lisp (`rove:run`, `fiveam:run!`), `rove
shop.asd`, or 40ants/run-tests.

## `coverage`

sb-cover instruments SBCL's compiled code for expression and branch coverage: `(require :sb-cover)` on the command
line or in a script CI loads, when the tests run; 40ants/run-tests with a `coveralls-token` does the same.

## `platform-matrix`

The toolchains are Lisp implementations, as Roswell names them (`sbcl-bin`, `ccl-bin`, `ecl`, `abcl-bin`, with a
version after a slash): the `LISP` variable 40ants/setup-lisp reads, `ros install` or `ros use`, a matrix key `lisp`,
or a clfoundation image.

## `compiler-warnings`

SBCL's compiler warns; sblint runs it over the system definition in CI and reports the warnings (`sblint shop.asd`).

## `warnings-as-errors`

A compiler warning fails the build: `(setf uiop:*compile-file-warnings-behaviour* :error)` (or
`*compile-file-failure-behaviour*`) in CI, in the system definition or in a script.

## `static-analysis`

sblint, the compiler's warnings over the whole system.

## `committed-artifacts`

Compiled files: SBCL's `*.fasl`, CCL's `*.lx64fsl` and `*.dx64fsl`, ECL's and CLISP's `*.fas`; and `.qlot/`.

## `vcs-ignore`

`*.fasl` (or the other implementations' compiled files) and `.qlot/`.

## Not judged

Common Lisp has no standard formatter (`code-formatting`), and no type checker, code security scanner, dependency
auditor, fuzzer or mutation testing tool the validator knows; lizard does not parse it (`function-limits`); Qlot's
`qlfile.lock` is left to `dependency-management`; a Lisp image builds no debug or release configuration
(`ci-build-types`, `hardening`, `cxx-extensions`).
