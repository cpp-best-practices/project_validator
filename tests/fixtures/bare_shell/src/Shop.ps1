function Get-Total($Prices) {
    $sum = 0
    foreach ($price in $Prices) { $sum += $price }
    $sum
}
