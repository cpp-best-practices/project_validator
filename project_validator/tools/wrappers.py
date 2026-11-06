"""Programs that run the command that follows them (`sudo make`, `emcmake cmake`, `xvfb-run npm test`), shared by
every language: each is a launcher (see `project_validator.facts.expansion.launcher`)."""

from project_validator.facts.expansion import launcher

WRAPPERS = launcher(
    "wrappers",
    (
        *((name,) for name in ("sudo", "time", "nice", "env", "nohup", "xvfb-run", "catchsegv")),
        *((name,) for name in ("emcmake", "emmake", "emconfigure", "scan-build", "ccache", "sccache")),
    ),
    with_values=frozenset({"-u", "--user", "-g", "--group", "-n", "--adjustment"}),
)
