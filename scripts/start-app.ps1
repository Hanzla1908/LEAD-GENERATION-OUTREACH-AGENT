# Starts the backend (port 8000) and the frontend (port 5173) in the background.
# Safe to run more than once: a server that already answers is left alone.
# Run with -Stop to stop both.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start-app.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start-app.ps1 -Stop

param([switch]$Stop)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$startupLog = Join-Path $logDir 'startup.log'

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Add-Content -Path $startupLog
}

function Test-Url($url) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $url).StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-Port($port) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerId in $owners) {
        Stop-Process -Id $ownerId -Force -ErrorAction SilentlyContinue
        Write-Log "stopped process $ownerId on port $port"
    }
}

function Wait-Url($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-Url $url) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

if ($Stop) {
    Stop-Port 8000
    Stop-Port 5173
    Write-Log 'stop requested'
    return
}

Write-Log 'start requested'

# Backend
if (-not (Test-Url 'http://127.0.0.1:8000/health')) {
    # A process may hold the port without answering (for example, left over from a crash). Free the port first.
    Stop-Port 8000
    Start-Process -FilePath (Join-Path $root 'backend\.venv\Scripts\python.exe') `
        -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory (Join-Path $root 'backend') `
        -RedirectStandardOutput (Join-Path $logDir 'backend.log') `
        -RedirectStandardError (Join-Path $logDir 'backend.err.log') `
        -WindowStyle Hidden
    Write-Log 'backend launched'
}

# Frontend
if (-not (Test-Url 'http://127.0.0.1:5173/')) {
    Stop-Port 5173
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort' `
        -WorkingDirectory (Join-Path $root 'frontend') `
        -RedirectStandardOutput (Join-Path $logDir 'frontend.log') `
        -RedirectStandardError (Join-Path $logDir 'frontend.err.log') `
        -WindowStyle Hidden
    Write-Log 'frontend launched'
}

$backendUp = Wait-Url 'http://127.0.0.1:8000/health' 90
$frontendUp = Wait-Url 'http://127.0.0.1:5173/' 90
Write-Log "backend up: $backendUp; frontend up: $frontendUp"
