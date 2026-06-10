$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $root ".env"

Write-Host "Configure the local AI vision API." -ForegroundColor Cyan
Write-Host "The API key will be stored only in: $envPath"

$secureKey = Read-Host "AI API Key" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
}

$model = Read-Host "Vision model name"
$baseUrl = Read-Host "OpenAI-compatible base URL [https://api.openai.com/v1]"
if ([string]::IsNullOrWhiteSpace($baseUrl)) {
    $baseUrl = "https://api.openai.com/v1"
}

if ([string]::IsNullOrWhiteSpace($apiKey) -or [string]::IsNullOrWhiteSpace($model)) {
    throw "API key and model name are required."
}
if ($apiKey.Contains("`n") -or $model.Contains("`n") -or $baseUrl.Contains("`n")) {
    throw "Configuration values cannot contain newlines."
}

$content = @(
    "AI_API_KEY=$apiKey"
    "AI_MODEL=$model"
    "AI_BASE_URL=$($baseUrl.TrimEnd('/'))"
) -join [Environment]::NewLine
[IO.File]::WriteAllText($envPath, $content, [Text.UTF8Encoding]::new($false))

$health = $null
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3
}
catch {
    Write-Host "Saved. Start the service with: python .\web_app.py" -ForegroundColor Yellow
    exit 0
}

if ($health.ai_configured) {
    Write-Host "Saved and loaded successfully." -ForegroundColor Green
    Write-Host "Model: $($health.ai.model)"
    Write-Host "Base URL: $($health.ai.base_url)"
}
else {
    Write-Host "Saved, but the running service did not load the configuration." -ForegroundColor Red
}
