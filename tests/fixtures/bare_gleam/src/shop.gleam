pub fn total(prices: List(Int)) -> Int {
  case prices {
    [] -> 0
    [first, ..rest] -> first + total(rest)
  }
}
