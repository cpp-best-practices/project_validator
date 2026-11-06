namespace App.Tests;

public class CalculatorTests
{
    [Fact]
    public void Adds() => Assert.Equal(3, Calculator.Add(1, 2));
}
