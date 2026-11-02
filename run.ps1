# Sets up on first run, then starts both servers. Open http://localhost:3000
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root "backend\.venv")
    & $python -m pip install -q -r (Join-Path $root "backend\requirements.txt")
    & $python -m playwright install chromium
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    npm --prefix (Join-Path $root "frontend") install
}
if (-not (Test-Path (Join-Path $root "frontend\.next\BUILD_ID"))) {
    npm --prefix (Join-Path $root "frontend") run build
}

$backend = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory (Join-Path $root "backend") -PassThru -NoNewWindow
try {
    Write-Host "Entitled is starting at http://localhost:3000 (Ctrl+C to stop)"
    npm --prefix (Join-Path $root "frontend") run start
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
}
