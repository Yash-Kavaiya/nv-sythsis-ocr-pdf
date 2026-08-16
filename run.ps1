# One-command dev server: deps + env + uvicorn (+ optional Vite).
#   .\run.ps1                          SPA built/served by FastAPI on :8000
#   $env:PORT=9000; .\run.ps1
#   $env:DEV_FRONTEND='1'; .\run.ps1   dual-process: Vite :5173 + API on PORT
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Force UTF-8: the real data-designer package logs emoji via `rich`, which
# crashes on Windows cp1252 consoles; uvicorn also benefits from it.
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $env:PORT) { $env:PORT = '8000' }

# .env is optional (and gitignored): KEY=value lines, loaded into the app's
# environment. The app itself only reads os.environ, so this is enough.
if (Test-Path .env) {
  foreach ($line in Get-Content .env) {
    if ($line -match '^\s*([^#=]+)=(.*)$') {
      [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
  }
}

if ($env:NVIDIA_API_KEY) {
  "NVIDIA_API_KEY set ($($env:NVIDIA_API_KEY.Substring(0,7))...) - LLM-backed generation enabled"
} else {
  "NVIDIA_API_KEY not set - offline Faker fallback mode"
}

pip install -q -r requirements.txt

$frontendDir = Join-Path $PSScriptRoot 'frontend'
$distDir = Join-Path $frontendDir 'dist'
$pkgJson = Join-Path $frontendDir 'package.json'

if ($env:DEV_FRONTEND -eq '1') {
  if (Test-Path $pkgJson) {
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
      Push-Location $frontendDir
      npm install
      Pop-Location
    }
    Start-Job -Name 'vite-dev' -ScriptBlock {
      param($dir)
      Set-Location $dir
      npm run dev
    } -ArgumentList $frontendDir | Out-Null
    "Wizard UI  http://localhost:5173  (Vite dev; /api proxied to backend)"
    "API        http://localhost:$($env:PORT)"
  } else {
    "DEV_FRONTEND=1 but frontend/package.json not found — starting API only"
  }
} elseif (Test-Path $pkgJson) {
  if (-not (Test-Path $distDir)) {
    "Building frontend (frontend/dist missing)..."
    Push-Location $frontendDir
    if (-not (Test-Path 'node_modules')) { npm install }
    npm run build
    Pop-Location
  }
  "Wizard UI  http://localhost:$($env:PORT)  (React SPA)"
  "Legacy UI  http://localhost:$($env:PORT)/legacy/"
} else {
  "Studio     http://localhost:$($env:PORT)"
  "Eval Lab   http://localhost:$($env:PORT)/eval.html"
}

uvicorn app.main:app --host 0.0.0.0 --port $env:PORT --reload
