BeforeAll {
    Import-Module "$PSScriptRoot/../src/Shop.psm1" -Force
}

Describe 'Get-Total' {
    It 'sums the prices' {
        Get-Total -Prices 1, 2, 3 | Should -Be 6
    }

    It 'an empty cart' {
        Get-Total -Prices @() | Should -Be 0
    }
}

Describe 'Get-Discounted' {
    It 'takes the percentage off' {
        Get-Discounted -Price 100 -Percent 10 | Should -Be 90
    }

    It 'ignores a negative percentage' {
        Get-Discounted -Price 100 -Percent -5 | Should -Be 100
    }
}
