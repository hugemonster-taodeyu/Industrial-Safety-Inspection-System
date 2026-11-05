param([Parameter(Mandatory = $true)][ValidateSet("stop", "wait")][string]$Action)
if ($Action -eq "stop") {
    Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    exit 0
}
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri http://127.0.0.1:5173/ -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) { exit 0 }
    } catch {}
    Start-Sleep -Milliseconds 500
}
exit 1
