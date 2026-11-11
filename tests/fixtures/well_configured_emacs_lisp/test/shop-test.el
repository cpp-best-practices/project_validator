;;; shop-test.el --- Tests for shop  -*- lexical-binding: t; -*-

;;; Commentary:

;; ERT tests of the prices, with undercover.el counting the lines they run.

;;; Code:

(require 'ert)

(when (require 'undercover nil t)
  (undercover "shop.el" (:report-format 'lcov) (:send-report nil)))

(require 'shop)

(ert-deftest shop-total-sums-the-prices ()
  (should (= 6 (shop-total '(1 2 3))))
  (should (= 0 (shop-total '()))))

(ert-deftest shop-discounted-takes-the-percentage-off ()
  (should (= 90 (shop-discounted 100 10)))
  (should (= 100 (shop-discounted 100 -5))))

(provide 'shop-test)
;;; shop-test.el ends here
