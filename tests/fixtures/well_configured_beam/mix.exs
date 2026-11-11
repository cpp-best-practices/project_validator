defmodule Shop.MixProject do
  use Mix.Project

  def project do
    [
      app: :shop,
      version: "0.1.0",
      elixir: "~> 1.17",
      elixirc_options: [warnings_as_errors: true],
      erlc_options: [:warnings_as_errors, :warn_missing_spec, :warn_export_vars],
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      aliases: aliases(),
      dialyzer: [flags: [:underspecs, :unmatched_returns]],
      test_coverage: [threshold: 90]
    ]
  end

  def application do
    [extra_applications: [:logger]]
  end

  defp deps do
    [
      {:jason, "~> 1.4"},
      {:credo, "~> 1.7", only: [:dev, :test], runtime: false},
      {:dialyxir, "~> 1.4", only: [:dev, :test], runtime: false},
      {:mix_audit, "~> 2.1", only: [:dev, :test], runtime: false},
      {:sobelow, "~> 0.13", only: [:dev, :test], runtime: false}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get"],
      lint: ["format --check-formatted", "credo --strict"]
    ]
  end
end
