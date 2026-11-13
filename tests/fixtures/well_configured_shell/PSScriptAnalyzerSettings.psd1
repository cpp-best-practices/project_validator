@{
    Severity            = @('Error', 'Warning', 'Information')
    IncludeDefaultRules = $true
    Rules               = @{
        PSUseConsistentIndentation = @{ Enable = $true; IndentationSize = 4 }
        PSUseConsistentWhitespace  = @{ Enable = $true }
    }
}
