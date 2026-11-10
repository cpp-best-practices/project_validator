"""Programs that run the command that follows them (`sudo make`, `emcmake cmake`, `xvfb-run npm test`,
`timeout 5m make check`, `find … | xargs clang-format`), shared by every language: each is a launcher (see
`project_validator.facts.expansion.launcher`)."""

from project_validator.facts.expansion import launcher

WRAPPERS = launcher(
    "wrappers",
    (
        *((name,) for name in ("sudo", "time", "nice", "env", "nohup", "xvfb-run", "catchsegv")),
        *((name,) for name in ("emcmake", "emmake", "emconfigure", "scan-build", "ccache", "sccache")),
    ),
    with_values=frozenset({"-u", "--user", "-g", "--group", "-n", "--adjustment"}),
)
# xargs runs its command with the arguments it reads appended; they are not known.
XARGS = launcher(
    "xargs",
    (("xargs",),),
    with_values=frozenset(
        {"-n", "-P", "-I", "-L", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter", "--arg-file"}
    ),
)
# timeout runs its command after a duration and its options (`timeout --signal=INT -k 2m 30m mutmut run`).
TIMEOUT = launcher(
    "timeout", (("timeout",),), with_values=frozenset({"-s", "--signal", "-k", "--kill-after"}), positionals=1
)
