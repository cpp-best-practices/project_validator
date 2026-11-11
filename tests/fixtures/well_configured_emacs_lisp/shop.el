;;; shop.el --- Prices of the shop's items  -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Example Maintainer

;; Author: Example Maintainer <maintainer@example.com>
;; URL: https://github.com/example/shop
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: convenience

;; This file is not part of GNU Emacs.

;;; Commentary:

;; Sums the prices of the shop's items and takes percentages off them.

;;; Code:

(defun shop-total (prices)
  "The sum of PRICES."
  (apply #'+ prices))

(defun shop-discounted (price percent)
  "PRICE with PERCENT taken off; a percentage of zero or less changes nothing."
  (if (<= percent 0)
      price
    (- price (/ (* price percent) 100))))

(provide 'shop)
;;; shop.el ends here
