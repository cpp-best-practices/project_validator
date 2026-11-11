local shop = require("shop")

describe("shop", function()
   it("sums the prices", function()
      assert.are.equal(7, shop.total({ { "tea", 3 }, { "cake", 4 } }))
   end)
end)
