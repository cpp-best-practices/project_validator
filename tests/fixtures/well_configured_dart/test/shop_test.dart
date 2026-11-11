import 'package:shop/shop.dart';
import 'package:test/test.dart';

void main() {
  test('sums the prices', () {
    expect(total([('tea', 3), ('cake', 4)]), 7);
  });
}
