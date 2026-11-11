use strict;
use warnings;
use ExtUtils::MakeMaker;

WriteMakefile(
    NAME             => 'Shop',
    AUTHOR           => 'Example Maintainer <maintainer@example.com>',
    VERSION_FROM     => 'lib/Shop.pm',
    ABSTRACT_FROM    => 'lib/Shop.pm',
    LICENSE          => 'mit',
    MIN_PERL_VERSION => '5.016',
    PREREQ_PM        => {},
    TEST_REQUIRES    => {
        'Test::More'     => '0.98',
        'Test::Warnings' => '0.030',
    },
    META_MERGE => { 'meta-spec' => { version => 2 } },
);
