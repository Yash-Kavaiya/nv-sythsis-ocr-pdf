# One-command dev server: deps + env + uvicorn.
#   .\run.ps1              start on :8000
#   $env:PORT=9000; .\run.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

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
"Studio   http://localhost:$($env:PORT)"
"Eval Lab http://localhost:$($env:PORT)/eval.html"
uvicorn app.main:app --host 0.0.0.0 --port $env:PORT --reload
