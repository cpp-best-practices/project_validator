rockspec_format = "3.0"
package = "shop"
version = "dev-1"
source = {
   url = "git+https://github.com/example/shop.git"
}
description = {
   summary = "Prices of the shop's items.",
   license = "MIT"
}
dependencies = {
   "lua >= 5.1"
}
test_dependencies = {
   "busted",
   "luacov"
}
build = {
   type = "builtin",
   modules = {
      ["shop"] = "src/shop/init.lua"
   }
}
test = {
   type = "busted"
}
