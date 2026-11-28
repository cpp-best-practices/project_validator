"""Ruby: managed with Bundler, judged by the Ruby versions and implementations CI runs.

Ruby projects run their tools through Rake (`bundle exec rake`): the Rakefile defines the test and lint tasks
(`RSpec::Core::RakeTask`, `RuboCop::RakeTask`) and the default task that runs them. So the Rakefile counts as CI
configuration when CI runs rake."""

from __future__ import annotations

import re

from project_validator.build_systems.model import standalone_package
from project_validator.ecosystems.model import VERSION, BuildSystem, Ecosystem, subcommands, toolchain_patterns
from project_validator.facts.axes import versions_axis
from project_validator.facts.dependencies import Dependencies, Lock, PackageManager, lockfile_reader, manifest_reader
from project_validator.facts.licenses import declared_license_reader
from project_validator.facts.outputs import BuildOutput, directories, ignored_at_top_level

RUBY_LANGUAGE = "Ruby"


RUBY_ONLY = frozenset({RUBY_LANGUAGE})


GEMFILE = "Gemfile"


BUNDLER = BuildSystem(name="Bundler", files=(GEMFILE, "*.gemspec"), languages=RUBY_ONLY, standalone=standalone_package)


RUNS_RAKE = re.compile(r"(?<![\w-])rake\b")


TEST_HELPERS = (".simplecov", "spec/spec_helper.rb", "spec/rails_helper.rb", "test/test_helper.rb")


GEM = re.compile(r"^\s*gem\s+[\"']", re.MULTILINE)


GEMSPEC_DEPENDENCY = re.compile(r"\.add_(?:runtime_|development_)?dependency\b")


_GEM_NAME = re.compile(r"""^\s*gem\s+["'](?P<name>[^"']+)["'](?P<rest>[^\n]*)""", re.MULTILINE)
_GROUP = re.compile(r"^\s*group\b(?P<groups>[^\n]*?)\bdo\b", re.MULTILINE)
_END = re.compile(r"^\s*end\b", re.MULTILINE)
# The groups only a project's development installs.
_DEVELOPMENT = re.compile(r":(?:development|test)\b|\b(?:development|test):")


def _gemfile_dependencies(_path: str, text: str) -> Dependencies:
    """The gems a Gemfile names; those in a development or test group (a `group ... do` block, or a `group:` option)
    are its development's."""
    direct: list[str] = []
    development: list[str] = []
    groups: list[bool] = []
    for line in text.splitlines():
        if found := _GROUP.match(line):
            groups.append(bool(_DEVELOPMENT.search(found["groups"])))
        elif _END.match(line) and groups:
            groups.pop()
        elif found := _GEM_NAME.match(line):
            developing = any(groups) or bool(_DEVELOPMENT.search(found["rest"]))
            (development if developing else direct).append(found["name"])
    return direct, development


GEMFILE_DEPENDENCIES = manifest_reader(
    name="Gemfile dependencies",
    manager="Bundler",
    files=(GEMFILE,),
    declares=lambda _path, text: bool(GEM.search(text)),
    lists=_gemfile_dependencies,
)


# A gem's users resolve its dependencies themselves.
_GEMSPEC_NAMED = re.compile(r"""\.add_(?P<kind>runtime_|development_)?dependency\b\s*\(?\s*["'](?P<name>[^"']+)""")


def _gemspec_dependencies(_path: str, text: str) -> Dependencies:
    found = [(match["kind"] == "development_", match["name"]) for match in _GEMSPEC_NAMED.finditer(text)]
    return [name for developing, name in found if not developing], [name for developing, name in found if developing]


GEMSPEC_DEPENDENCIES = manifest_reader(
    name="gemspec dependencies",
    manager="Bundler",
    files=("*.gemspec",),
    declares=lambda _path, text: bool(GEMSPEC_DEPENDENCY.search(text)),
    lists=_gemspec_dependencies,
    library=lambda _path, _text: True,
)


GEMFILE_LOCK = lockfile_reader(manager="Bundler", files=("Gemfile.lock",))


BUNDLER_PACKAGES = PackageManager(
    name="Bundler",
    languages=RUBY_ONLY,
    lock=Lock.APPLICATIONS,
    lock_hint="commit Gemfile.lock, so the application is installed with the gems it was tested with",
)


GEMSPEC_LICENSES = re.compile(r"""\.licenses?\s*=\s*(?:\[(?P<list>[^\]]*)\]|["'](?P<one>[^"']+)["'])""")


def _gemspec_license(text: str) -> str | None:
    """A gemspec's licenses are a choice, as an SPDX expression joins them with OR."""
    match = GEMSPEC_LICENSES.search(text)
    if match is None:
        return None
    return match["one"] or " OR ".join(re.findall(r"""["']([^"']+)["']""", match["list"])) or None


GEMSPEC_LICENSE = declared_license_reader(
    name="gemspec license", files=("*.gemspec",), languages=RUBY_ONLY, declared=_gemspec_license
)


BUNDLE = BuildOutput(
    languages=RUBY_ONLY,
    name="the installed gems",
    globs=ignored_at_top_level(r"\.bundle|vendor/bundle"),
    paths=directories(".bundle", "vendor/bundle"),
    hint="consider ignoring .bundle/ and vendor/bundle/ (and coverage/, pkg/ and *.gem)",
    # A committed vendor/bundle/ is reported by dependency-management, as any committed vendor/ is.
    artifacts=(".bundle/", "/coverage/", "/pkg/", "*.gem"),
)


_RUBY_VERSION = r"(\d+\.\d+(?:\.\d+)?|head|(?:jruby|truffleruby)(?:-[\w.]+)?)"


RUBY = Ecosystem(
    label=RUBY_LANGUAGE,
    links={RUBY_LANGUAGE: "https://www.ruby-lang.org/"},
    languages=RUBY_ONLY,
    build_systems=(BUNDLER,),
    source_suffixes={".rb": RUBY_LANGUAGE, ".rake": RUBY_LANGUAGE},
    # Rack configuration and ERB templates belong to Ruby projects, but name no language on their own.
    ambiguous_suffixes={".ru": None, ".erb": None, ".feature": None},
    toolchain=toolchain_patterns(
        RUBY_LANGUAGE,
        version=_RUBY_VERSION,
        inputs=("ruby-version",),
        images=("ruby",),
        image_version=VERSION,
        programs=(*subcommands("bundle", "exec", "install"), "rake", "rspec"),
        setup=("ruby",),
    ),
)


RUBY_VERSIONS = versions_axis("Ruby version", RUBY_LANGUAGE, RUBY_ONLY)
