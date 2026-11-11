/// The total price of [items], each a name and a price.
int total(Iterable<(String, int)> items) => items.fold(0, (sum, item) => sum + item.$2);
