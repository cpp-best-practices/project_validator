defmodule Shop do
  @moduledoc "Prices of the shop's items."

  @spec total([{String.t(), non_neg_integer()}]) :: non_neg_integer()
  def total(items), do: items |> Enum.map(fn {_name, price} -> price end) |> Enum.sum()
end
