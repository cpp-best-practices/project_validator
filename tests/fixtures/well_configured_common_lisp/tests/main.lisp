(defpackage #:shop/tests
  (:use #:cl #:fiveam)
  (:export #:shop-suite))

(in-package #:shop/tests)

(def-suite shop-suite
  :description "The shop's prices.")

(in-suite shop-suite)

(test total-sums-the-prices
  (is (= 6 (shop:total '(1 2 3))))
  (is (= 0 (shop:total '()))))

(test discounted-takes-the-percentage-off
  (is (= 90 (shop:discounted 100 10)))
  (is (= 100 (shop:discounted 100 -5))))
