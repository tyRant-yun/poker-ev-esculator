param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$url = "http://127.0.0.1:8000"
$healthUrl = "$url/api/health"

function Test-PokerLabService {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        return $health.ok -eq $true -and $health.service -eq "complete-hand-workbench"
    }
    catch {
        return $false
    }
}

if (-not (Test-PokerLabService)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python was not found. Install Python 3.10+ and add python to PATH."
    }

    $serverScript = Join-Path $root "web_app.py"
    $arguments = '"{0}" --host 127.0.0.1 --port 8000' -f $serverScript
    Start-Process `
        -FilePath $python.Source `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -WindowStyle Hidden

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-PokerLabService) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "Poker Lab failed to start. Check whether port 8000 is already in use."
    }
}

if ($NoBrowser) {
    Write-Output $url
}
else {
    Start-Process $url
}
