;;; shop.el --- Prices  -*- lexical-binding: t; -*-

(defun shop-total (prices)
  (apply (function +) prices))

(provide (quote shop))
;;; shop.el ends here
