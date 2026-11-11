local shop = {}
function shop.total(items)
   local sum = 0
   for _, item in ipairs(items) do sum = sum + item[2] end
   return sum
end
return shop
