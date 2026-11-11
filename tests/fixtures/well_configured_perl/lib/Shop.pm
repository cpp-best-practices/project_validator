package Shop;

use strict;
use warnings;

our $VERSION = '0.01';

=head1 NAME

Shop - prices of the shop's items

=head1 SYNOPSIS

    my $sum = Shop::total(1, 2, 3);

=cut

sub total {
    my $sum = 0;
    $sum += $_ for @_;
    return $sum;
}

sub discounted {
    my ( $price, $percent ) = @_;
    return $price if $percent <= 0;
    return $price - int( $price * $percent / 100 );
}

1;
