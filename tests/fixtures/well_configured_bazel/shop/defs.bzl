def shop_prices(name):
    native.filegroup(
        name = name,
        srcs = ["prices.txt"],
    )
