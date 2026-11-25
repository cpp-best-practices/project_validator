"""Runners of other commands: `docker run img make test` runs `make test` in the image, read as a command of the
job; an Earthly target (`earthly +test`) runs the RUN commands of the target in the Earthfile (upstream #264)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from project_validator.core import Context
from project_validator.facts import Command, Origin, Unknown, resolved
from project_validator.facts.expansion import CommandExpander, Expansion, Invocation, Launched, Script, joined
from project_validator.facts.shell import command_line, split_words

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


# A target of an Earthfile: its name at the start of a line, then its indented commands.
_TARGET = re.compile(r"^(?P<name>[A-Za-z][\w.-]*):\s*$")
_RUN_OPTIONS = re.compile(r"^(?:--[\w-]+(?:=\S+)?\s+)*")


def _target_lines(text: str, target: str) -> list[str] | None:
    """The commands of `target` in an Earthfile, each on one line (continuations joined); None without the target."""
    lines = text.replace("\\\n", " ").splitlines()
    for index, line in enumerate(lines):
        if (match := _TARGET.match(line)) is not None and match["name"] == target:
            body = []
            for following in lines[index + 1 :]:
                if following.strip() and not following[:1].isspace():
                    break
                body.append(following.strip())
            return [found for found in body if found and not found.startswith("#")]
    return None


def _run_text(arguments: str) -> str:
    """The shell text of a RUN: its shell form, without RUN's own options, or its exec form's words."""
    arguments = _RUN_OPTIONS.sub("", arguments)
    if arguments.startswith("["):
        try:
            words = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        return command_line(map(str, words)) if isinstance(words, list) else arguments
    return arguments


def _earthfile_expansions(path: str, target: str, lines: list[str]) -> Iterator[Expansion]:
    for number, line in enumerate(lines):
        keyword, _, arguments = line.partition(" ")
        origin = Origin(path=path, at=(target, number))
        if keyword == "RUN":
            yield Script(text=_run_text(arguments.strip()), origin=origin)
        elif keyword == "BUILD" and arguments.strip():
            reference = split_words(arguments)[-1]
            yield Invocation(argv=("earthly", reference), line=line, origin=origin)


def _earthly(command: Command, context: Context) -> list[Expansion] | None:
    """`earthly +target` (or `./dir+target`): the RUN commands of the target in its Earthfile, and the targets it
    BUILDs; a target of another repository, or one that is not defined, is unknown."""
    argv = resolved(command)
    if argv[:1] != ("earthly",):
        return None
    targets = [word for word in argv[1:] if "+" in word and not word.startswith("-")]
    if not targets:
        return [Unknown(origin=command.origin, subject=f"the command {command.line!r}", reason="it names no target")]
    directory, _, target = targets[0].rpartition("+")
    subject = f"the Earthly target {targets[0]}"
    if directory and not directory.startswith((".", "/")):
        return [Unknown(origin=command.origin, subject=subject, reason="Earthfiles of other repositories are not read")]
    path = joined(joined(command.directory, directory) if directory else command.directory, "Earthfile")
    if not context.project.exists(path):
        return [Unknown(origin=command.origin, subject=subject, reason="there is no Earthfile")]
    lines = _target_lines(context.project.read_text(path), target)
    if lines is None:
        return [Unknown(origin=command.origin, subject=subject, reason=f"the Earthfile defines no target {target}")]
    return list(_earthfile_expansions(path, target, lines))


DOCKER_RUN = CommandExpander(name="docker run", expand=_docker_run)
EARTHLY = CommandExpander(name="earthly", expand=_earthly)
