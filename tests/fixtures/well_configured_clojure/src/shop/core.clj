(ns shop.core
  "Prices of the shop's items.")

(set! *warn-on-reflection* true)

(defn total
  "The sum of `prices`."
  [prices]
  (reduce + 0 prices))

(defn discounted
  "`price` with `percent` taken off; a percentage of zero or less changes nothing."
  [price percent]
  (if (<= percent 0)
    price
    (- price (quot (* price percent) 100))))
