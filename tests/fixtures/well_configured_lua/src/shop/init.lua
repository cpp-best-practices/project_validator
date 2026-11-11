--- Prices of the shop's items.
local shop = {}

--- The total price of `items`, each a name and a price.
---@param items { [1]: string, [2]: integer }[]
---@return integer
function shop.total(items)
   local sum = 0
   for _, item in ipairs(items) do
      sum = sum + item[2]
   end
   return sum
end

return shop
