function Get-Total {
    <#
    .SYNOPSIS
    Sums the prices.
    #>
    param([int[]]$Prices)
    $sum = 0
    foreach ($price in $Prices) {
        $sum += $price
    }
    $sum
}

function Get-Discounted {
    <#
    .SYNOPSIS
    Takes a percentage off a price; a negative percentage is ignored.
    #>
    param([int]$Price, [int]$Percent)
    if ($Percent -lt 0) {
        return $Price
    }
    $Price - [math]::Floor($Price * $Percent / 100)
}

Export-ModuleMember -Function Get-Total, Get-Discounted
