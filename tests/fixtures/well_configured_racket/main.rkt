#lang racket/base

;; Prices of the shop's items.

(provide total discounted)

;; The sum of the prices.
(define (total prices)
  (apply + prices))

;; A price with a percentage taken off; a percentage of zero or less changes nothing.
(define (discounted price percent)
  (if (<= percent 0)
      price
      (- price (quotient (* price percent) 100))))

(module+ test
  (require rackunit)
  (check-equal? (total '(1 2 3)) 6)
  (check-equal? (total '()) 0)
  (check-equal? (discounted 100 10) 90)
  (check-equal? (discounted 100 -5) 100))
