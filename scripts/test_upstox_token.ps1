# Tests a personal Upstox live access token directly against the official profile API.
# It does not save or print the token. Windows PowerShell 5.1+.
$ErrorActionPreference = 'Stop'
Write-Host 'Upstox official API token check (no credentials will be saved)'
$secure = Read-Host -Prompt 'Paste current Upstox LIVE OAuth access_token' -AsSecureString
$ptr = [IntPtr]::Zero
$access = $null
try {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $access = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim()
    $access = $access -replace '^Bearer\s+', ''
    $access = $access.Trim().Trim('"').Trim("'")
    if (-not $access -or $access -match '\s') { throw 'Paste only the Upstox access_token value.' }
    $headers = @{ Accept = 'application/json'; Authorization = ('Bearer ' + $access) }
    $result = Invoke-RestMethod -Method Get -Uri 'https://api.upstox.com/v2/user/profile' -Headers $headers -TimeoutSec 20
    if ($result.status -eq 'success' -and $result.data.user_id) {
        Write-Host 'SUCCESS: Upstox recognizes this access token.' -ForegroundColor Green
        Write-Host ('User ID: ' + $result.data.user_id)
        Write-Host 'Try the updated TradeVerse login with the same token.'
    } else {
        Write-Host 'The profile request returned an unexpected response.' -ForegroundColor Yellow
    }
} catch {
    # Avoid printing the raw exception, which can include request details in some PowerShell versions.
    $status = ''
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
        $status = [int]$_.Exception.Response.StatusCode
    }
    if ($status) {
        Write-Host ("Upstox returned HTTP " + $status) -ForegroundColor Yellow
        Write-Host '401: check for a new live access token; 403: check permissions/token type.'
    } else {
        Write-Host 'Request failed. Check your internet connection and that you entered an access token.' -ForegroundColor Yellow
    }
} finally {
    $access = $null
    $headers = $null
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}
