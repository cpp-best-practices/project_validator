defmodule Shop.MixProject do
  use Mix.Project

  def project do
    [app: :shop, version: "0.1.0", elixir: "~> 1.17", deps: deps()]
  end

  defp deps do
    [{:jason, "~> 1.4"}]
  end
end
