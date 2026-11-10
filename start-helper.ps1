param(
    [Parameter(Mandatory = $true)][ValidateSet("stop", "wait", "say")][string]$Action,
    [string]$Name
)

$messages = @{
    stopping          = "正在停止已有的后端和页面..."
    "starting-backend"  = "正在启动后端..."
    "starting-frontend" = "正在启动页面..."
    waiting           = "等待页面就绪..."
    opened            = "已打开 http://127.0.0.1:5173/"
    notready          = "页面在 30 秒内没有就绪，请查看 frontend 窗口里的报错。"
}

if ($Action -eq "say") {
    Write-Host $messages[$Name]
    exit 0
}

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
