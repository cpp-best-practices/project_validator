"""
Prices of the shop's items.
"""
module Shop

export total, discounted

"""
    total(prices)

The sum of `prices`.
"""
total(prices) = sum(prices; init = 0)

"""
    discounted(price, percent)

`price` with `percent` taken off; a percentage of zero or less changes nothing.
"""
discounted(price, percent) = percent <= 0 ? price : price - price * percent ÷ 100

end
