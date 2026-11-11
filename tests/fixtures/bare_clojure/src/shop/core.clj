(ns shop.core)

(defn total [prices] (reduce + 0 prices))
