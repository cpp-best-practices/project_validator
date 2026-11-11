use strict;
use warnings;
use Test::More;
use Test::Warnings;

use Shop;

is( Shop::total( 1, 2, 3 ), 6, 'sums the prices' );
is( Shop::total(),         0, 'an empty cart' );
is( Shop::discounted( 100, 10 ), 90,  'takes the percentage off' );
is( Shop::discounted( 100, -5 ), 100, 'ignores a negative percentage' );

done_testing;
