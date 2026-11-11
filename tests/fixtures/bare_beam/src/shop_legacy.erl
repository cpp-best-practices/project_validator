-module(shop_legacy).
-export([discount/2]).

discount(Price, Percent) ->
    Price - Price * Percent div 100.
