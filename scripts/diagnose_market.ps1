# Local-only, read-only market-data diagnostics. Never prints broker access tokens.
param([string]$Account = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$api = 'http://127.0.0.1:8000'
$headers = @{}
if ($env:APP_LOCAL_TOKEN) { $headers['X-Local-Token'] = $env:APP_LOCAL_TOKEN }
function Call-API([string]$url) {
    return Invoke-RestMethod -Uri ($api + $url) -Headers $headers -TimeoutSec 20
}
try {
    $health = Call-API '/api/health'
    Write-Host ('Backend: OK; connected accounts: ' + $health.connected_accounts) -ForegroundColor Green
    $accounts = @(Call-API '/api/accounts') | Where-Object { $_.connected -eq $true }
    if (-not $accounts -or $accounts.Count -eq 0) { Write-Warning 'No broker session connected. Log in through the application first.'; exit 2 }
    if (-not $Account) { $Account = $accounts[0].id }
    Write-Host ('Checking account: ' + $Account)
    $status = Call-API '/api/feeds/status'
    $feed = $status.PSObject.Properties[$Account]
    if ($null -ne $feed) {
        Write-Host ('Feed state: ' + $feed.Value.state + '; subscribed: ' + $feed.Value.subscribed)
        if ($feed.Value.error) { Write-Warning ('Feed error: ' + $feed.Value.error) }
        if ($null -ne $feed.Value.age_seconds) { Write-Host ('Last tick age (seconds): ' + $feed.Value.age_seconds) }
    } else { Write-Warning 'No active WebSocket subscriptions. Keep the chart open when running diagnostics.' }
    $path = '/api/history?account=' + [uri]::EscapeDataString($Account) + '&exchange=NSE&symbol=NIFTY&segment=IDX&interval=15m&limit=10'
    try {
        $candles = @(Call-API $path)
        Write-Host ('Cached NIFTY 15m candles (last 10): ' + $candles.Count)
        if ($candles.Count -gt 0) { Write-Host ('Oldest of last 10: ' + $candles[0].ts) }
    } catch { Write-Warning ('History cache query failed: ' + $_.Exception.Message) }
    if ($Account.StartsWith('upstox:')) {
        try {
            $body = @{ account = $Account; instruments = @(@{ exchange='NSE'; symbol='NIFTY'; segment='IDX' }) } | ConvertTo-Json -Depth 6
            $snap = Invoke-RestMethod -Method Post -Uri ($api + '/api/quotes/snapshot') -Headers $headers -Body $body -ContentType 'application/json' -TimeoutSec 20
            if ($snap.quotes.Count -gt 0) { Write-Host ('Upstox REST quote LTP: ' + $snap.quotes[0].ltp + ' (snapshot, not WebSocket)') -ForegroundColor Green }
            else { Write-Warning 'Upstox returned no NIFTY REST quote.' }
        } catch { Write-Warning ('Upstox REST snapshot failed: ' + $_.Exception.Message) }
    }
} catch { Write-Error ('Cannot reach backend: ' + $_.Exception.Message); exit 1 }
