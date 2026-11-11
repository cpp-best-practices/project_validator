#lang racket/base
(provide total)
(define (total prices) (apply + prices))
