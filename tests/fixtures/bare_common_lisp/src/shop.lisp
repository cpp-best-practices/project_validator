(defpackage #:shop (:use #:cl) (:export #:total))
(in-package #:shop)

(defun total (prices) (reduce (function +) prices))
