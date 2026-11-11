int total(Iterable<(String, int)> items) => items.fold(0, (sum, item) => sum + item.$2);
