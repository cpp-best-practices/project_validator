package shop

class ShopSuite extends munit.FunSuite:
  test("sums the prices") {
    assertEquals(Shop.total(Seq("tea" -> 3, "cake" -> 4)), 7)
  }
