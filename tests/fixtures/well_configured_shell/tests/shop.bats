#!/usr/bin/env bats

setup() {
  source "$BATS_TEST_DIRNAME/../src/shop.sh"
}

@test "sums the prices" {
  run total 1 2 3
  [ "$output" = "6" ]
}

@test "an empty cart" {
  run total
  [ "$output" = "0" ]
}

@test "takes the percentage off" {
  run discounted 100 10
  [ "$output" = "90" ]
}

@test "ignores a negative percentage" {
  run discounted 100 -5
  [ "$output" = "100" ]
}
