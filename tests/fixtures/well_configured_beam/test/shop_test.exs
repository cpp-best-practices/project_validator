defmodule ShopTest do
  use ExUnit.Case, async: true
  doctest Shop

  test "sums the prices" do
    assert Shop.total([{"tea", 3}, {"cake", 4}]) == 7
  end

  test "applies a discount" do
    assert :shop_legacy.discount(100, 25) == 75
  end
end
