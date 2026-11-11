%{
  configs: [
    %{
      name: "default",
      files: %{included: ["lib/", "test/"]},
      checks: %{enabled: [{Credo.Check.Readability.Specs, []}]}
    }
  ]
}
