-module(shop_legacy).
-export([discount/2]).

-spec discount(non_neg_integer(), non_neg_integer()) -> non_neg_integer().
discount(Price, Percent) when Percent >= 0, Percent =< 100 ->
    Price - Price * Percent div 100.
