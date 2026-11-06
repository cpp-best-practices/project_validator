<?php

declare(strict_types=1);

namespace App\Tests;

use App\Calculator;
use PHPUnit\Framework\TestCase;

final class CalculatorTest extends TestCase
{
    public function testAdds(): void
    {
        self::assertSame(3, (new Calculator())->add(1, 2));
    }
}
