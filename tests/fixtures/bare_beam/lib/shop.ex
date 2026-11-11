defmodule Shop do
  def total(items), do: items |> Enum.map(fn {_name, price} -> price end) |> Enum.sum()
end
