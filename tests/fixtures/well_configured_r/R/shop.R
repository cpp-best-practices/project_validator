#' The sum of the prices.
#'
#' @param prices A numeric vector.
#' @return The total.
#' @export
total <- function(prices) {
  sum(prices)
}

#' A price with a percentage taken off.
#'
#' @param price A number.
#' @param percent The percentage; zero or less changes nothing.
#' @return The discounted price.
#' @export
discounted <- function(price, percent) {
  if (percent <= 0) {
    return(price)
  }
  price - price * percent / 100
}
