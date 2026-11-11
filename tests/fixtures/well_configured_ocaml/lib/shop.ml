(* Prices of the shop's items. *)

let total prices = List.fold_left ( + ) 0 prices

let discounted ~percent price =
  if percent <= 0 then price else price - (price * percent / 100)
