;;;; Prices of the shop's items.

(defpackage #:shop
  (:use #:cl)
  (:export #:total #:discounted))

(in-package #:shop)

(defun total (prices)
  "The sum of PRICES."
  (reduce #'+ prices :initial-value 0))

(defun discounted (price percent)
  "PRICE with PERCENT taken off; a percentage of zero or less changes nothing."
  (if (<= percent 0)
      price
      (- price (floor (* price percent) 100))))
