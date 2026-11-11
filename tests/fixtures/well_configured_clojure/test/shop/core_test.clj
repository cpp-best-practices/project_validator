(ns shop.core-test
  (:require [clojure.test :refer [deftest is testing]]
            [shop.core :as shop]))

(deftest total-test
  (testing "sums the prices"
    (is (= 6 (shop/total [1 2 3])))
    (is (= 0 (shop/total [])))))

(deftest discounted-test
  (testing "takes the percentage off"
    (is (= 90 (shop/discounted 100 10)))
    (is (= 100 (shop/discounted 100 -5)))))
