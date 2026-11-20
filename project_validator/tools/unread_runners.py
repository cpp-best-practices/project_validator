"""Runners of other commands: `docker run img make test` runs `make test` in the image, read as a command of the
job; an Earthly target (`earthly +test`) runs what the checkout's reader does not follow, recorded as unknown."""

from __future__ import annotations

from project_validator.core import Context
from project_validator.facts import Command, Unknown, resolved
from project_validator.facts.expansion import CommandExpander, Expansion, Launched

# `docker run` (and `podman run`) options that take a value, as their own word unless written `--name=value`.
_WITH_VALUE = frozenset(
    {
        *("-v", "--volume", "-e", "--env", "--env-file", "-w", "--workdir", "--name", "-p", "--publish"),
        *("--entrypoint", "--network", "--net", "-u", "--user", "--platform", "--mount", "-l", "--label"),
        *("--cpus", "-m", "--memory", "--add-host", "--device", "--gpus", "-h", "--hostname", "--ulimit"),
        *("--cap-add", "--cap-drop", "--security-opt", "--tmpfs", "--shm-size", "--pull", "--ipc", "--pid"),
        *("--runtime", "--restart", "--log-driver", "--log-opt", "--cidfile", "--group-add", "--expose"),
    }
)
_ENGINES = frozenset({"docker", "podman"})
# Short options whose value may follow them in a group (`-itv "$PWD":/code`).
_SHORT_WITH_VALUE = frozenset(option[1] for option in _WITH_VALUE if len(option) == 2)


def _takes_value(option: str) -> bool:
    if option in _WITH_VALUE:
        return True
    return not option.startswith("--") and "=" not in option and option[-1] in _SHORT_WITH_VALUE


def _options(words: tuple[str, ...]) -> tuple[int, str | None, dict[str, str]]:
    """Where a `docker run`'s options end (at its image), its `--entrypoint`, and the variables `-e NAME=VALUE` sets."""
    index, entrypoint, env = 0, None, {}
    while index < len(words) and words[index].startswith("-"):
        option, value = words[index].partition("=")[0], words[index + 1] if index + 1 < len(words) else ""
        if "=" in words[index] and option.startswith("--"):
            value = words[index].partition("=")[2]
        if option == "--entrypoint":
            entrypoint = value
        elif option in ("-e", "--env") and "=" in value:
            name, _, setting = value.partition("=")
            env[name] = setting
        index += 2 if _takes_value(words[index]) else 1
    return index, entrypoint, env


def _docker_run(command: Command, _context: Context) -> list[Expansion] | None:
    """The command a `docker run` runs in its image: the `--entrypoint` with the words after the image, or those words
    when they are a command (none, or options of the image's own program, run nothing to read)."""
    argv = resolved(command)
    if len(argv) < 2 or argv[0] not in _ENGINES or argv[1] != "run":
        return None
    words = argv[2:]
    index, entrypoint, env = _options(words)
    end = index + 1
    while end < len(words) and words[index].startswith("${{") and "}}" not in words[end - 1]:
        end += 1  # an image an expression names, split at its spaces
    rest = words[end:]
    inner = (entrypoint, *rest) if entrypoint is not None else rest if rest[:1] and not rest[0].startswith("-") else ()
    return [Launched(argv=inner, env=env)] if inner and index < len(words) else None


def _earthly(command: Command, _context: Context) -> list[Expansion] | None:
    argv = resolved(command)
    if argv[:1] != ("earthly",):
        return None
    targets = [word for word in argv[1:] if word.startswith(("+", "./")) and "+" in word]
    reason = "Earthfiles are not read"
    subject = f"the Earthly target {targets[0]}" if targets else f"the command {command.line!r}"
    return [Unknown(origin=command.origin, subject=subject, reason=reason)]


DOCKER_RUN = CommandExpander(name="docker run", expand=_docker_run)
EARTHLY = CommandExpander(name="earthly", expand=_earthly)
