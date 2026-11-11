(defsystem "shop"
  :description "Prices of the shop's items."
  :author "Example Maintainer <maintainer@example.com>"
  :license "MIT"
  :version "0.1.0"
  :pathname "src"
  :components ((:file "shop"))
  :in-order-to ((test-op (test-op "shop/tests"))))

(defsystem "shop/tests"
  :depends-on ("shop" "fiveam")
  :pathname "tests"
  :components ((:file "main"))
  :perform (test-op (o c) (symbol-call :fiveam :run! (find-symbol* :shop-suite :shop/tests))))
