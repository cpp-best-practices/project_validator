#!/usr/bin/env bash
# Prices of the shop: the functions the scripts source.
set -euo pipefail

total() {
  local sum=0
  for price in "$@"; do
    sum=$((sum + price))
  done
  echo "$sum"
}

discounted() {
  local price=$1 percent=$2
  if ((percent < 0)); then
    echo "$price"
  else
    echo $((price - price * percent / 100))
  fi
}
