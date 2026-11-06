# Ruby

Recognised by `.rb` sources and Bundler (`Gemfile`). The Rakefile counts as CI configuration when CI runs rake.

## `tests-run`

`spec/**/*_spec.rb` or `test/**/*_test.rb` files run by rspec, `rake test` / `spec` or `rails test`, or by the
Rakefile's test tasks when CI runs rake.

## `coverage`

SimpleCov with `enable_coverage :branch` (in `.simplecov` or a test helper).

## `platform-matrix`

The toolchains are Ruby versions and implementations.

## `compiler-warnings`

Ruby's warnings are on while testing (`ruby -w`, `RUBYOPT=-w`, `$VERBOSE = true`, RSpec's `--warnings` /
`config.warnings`, or a test task's `warning = true`) and RuboCop or Standard runs.

## `type-checking`

Sorbet (`srb tc`) or Steep (`steep check`). Strict mode is a bonus: Sorbet's `# typed: strict`, or `D::Ruby.strict`
in a Steepfile.

## `code-formatting`

RuboCop (not `-a`), Standard or `stree check`; they have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs with a length limit, or RuboCop runs with `Metrics/MethodLength` not disabled (it is on by default).

## `static-analysis`

RuboCop, Standard or Reek.

## `security-scanning`

brakeman, or RuboCop, whose Security cops are on by default.

## `dependency-management`

Gems in the `Gemfile` (or a gemspec's dependencies) are locked by a committed `Gemfile.lock`, unless the project is a
gem (has a gemspec).

## `dependency-audit`

bundler-audit.

## `license`

The gemspec's `license` or `licenses`.

## `committed-artifacts`

`.bundle/`, `*.gem`, and a top-level `coverage/` or `pkg/`. A committed `vendor/bundle/` is reported by
`dependency-management`.

## `vcs-ignore`

`.bundle/` or `vendor/bundle/`.
