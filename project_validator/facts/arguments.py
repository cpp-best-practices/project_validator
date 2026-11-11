"""Reading a command's arguments: its program, its options and their values, and its positional arguments."""

from __future__ import annotations


def program(argv: tuple[str, ...]) -> str:
    """The name of the program `argv` runs, without its directory or a Windows suffix (`./vendor/bin/phpunit`)."""
    name = argv[0].replace("\\", "/").rsplit("/", 1)[-1] if argv else ""
    for suffix in (".exe", ".cmd", ".bat"):
        name = name.removesuffix(suffix)
    return name


def starts_with(argv: tuple[str, ...], *prefixes: tuple[str, ...]) -> tuple[str, ...] | None:
    """The first of `prefixes` that `argv` starts with: a program, by name (`./vendor/bin/phpunit` is `phpunit`), and
    the subcommands right after it (`("cargo", "test")`); None when it starts with none."""
    name = program(argv)
    return next(
        (prefix for prefix in prefixes if prefix and name == prefix[0] and argv[1 : len(prefix)] == prefix[1:]), None
    )


def has_option(argv: tuple[str, ...], *names: str) -> bool:
    """Whether `argv` gives one of the options `names`, alone or with a value (`--name=value`)."""
    return any(word in names or word.partition("=")[0] in names for word in argv[1:])


def short_flags(argv: tuple[str, ...]) -> frozenset[str]:
    """The one-letter flags given in `argv`, together or apart (`-bc`, `-b -c`)."""
    return frozenset(
        letter for word in argv[1:] if word.startswith("-") and not word.startswith("--") for letter in word[1:]
    )


def _value(word: str, following: str | None, name: str) -> str | None:
    if word == name:
        return following
    if word.startswith(f"{name}="):
        return word[len(name) + 1 :]
    if len(name) == 2 and word.startswith(name) and len(word) > 2:
        return word[2:]  # -Cvalue
    return None


def option_values(argv: tuple[str, ...], *names: str) -> list[str]:
    """The values of options `names` in `argv`, written `--name value`, `--name=value` or (one letter) `-Cvalue`."""
    following = [*argv[1:], None][: len(argv)]
    return [
        value
        for word, after in zip(argv, following, strict=True)
        for name in names
        if (value := _value(word, after, name)) is not None
    ]


def positional(argv: tuple[str, ...], with_values: frozenset[str] = frozenset()) -> tuple[list[str], dict[str, str]]:
    """The positional arguments after the program, and the values of the options in `with_values`.

    `--opt=value` and `--opt value` are both read; other options are skipped.
    """
    words: list[str] = []
    options: dict[str, str] = {}
    arguments = iter(argv[1:])
    for word in arguments:
        name, equals, value = word.partition("=")
        if name in with_values:
            options[name] = value if equals else next(arguments, "")
        elif not word.startswith("-"):
            words.append(word)
    return words, options


__all__ = ["has_option", "option_values", "positional", "program", "short_flags", "starts_with"]
