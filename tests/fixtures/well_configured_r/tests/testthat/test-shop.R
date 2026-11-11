test_that("total sums the prices", {
  expect_equal(total(c(1, 2, 3)), 6)
})

test_that("discounted takes the percentage off", {
  expect_equal(discounted(100, 10), 90)
  expect_equal(discounted(100, -5), 100)
})
