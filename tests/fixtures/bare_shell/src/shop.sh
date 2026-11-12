total() {
  sum=0
  for price in "$@"; do sum=$((sum + price)); done
  echo $sum
}
