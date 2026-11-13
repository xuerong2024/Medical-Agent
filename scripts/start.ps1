param([switch]$Build, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Force -Path '.runtime','data' | Out-Null
$localPython=Join-Path $projectRoot '.venv\Scripts\python.exe'
if ((Test-Path -LiteralPath '.env') -and ((Get-Content -LiteralPath '.env') -match '^LOCAL_POSTGRES=true$')) {
    & $localPython scripts\local_postgres.py
    if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL startup failed' }
}
if (Test-Path -LiteralPath '.env') {
    foreach ($line in Get-Content -LiteralPath '.env' -Encoding UTF8) {
        if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
        }
    }
}
$env:PYTHONUTF8 = '1'
$env:JAVA_TOOL_OPTIONS = '-Dfile.encoding=UTF-8'
$env:MEDAGENT_DATA_DIR = Join-Path $projectRoot 'data\worker'
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.runtime\pip-cache'
if (-not $env:PORT) { $env:PORT = '8080' }
if (-not $env:WORKER_URL) { $env:WORKER_URL = 'http://127.0.0.1:8090' }
foreach ($port in @([int]$env:PORT,8090)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is occupied. Stop the existing project with scripts/stop.ps1 or choose a free backend PORT." }
}
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed' }
    & $python -m pip install -r worker\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
}
$jar = Join-Path $projectRoot 'backend\target\medical-agent-0.1.0.jar'
if ($Build -or -not (Test-Path -LiteralPath $jar)) {
    & mvn -f backend\pom.xml "-Dmaven.repo.local=$projectRoot\.runtime\m2" -B -ntp package
    if ($LASTEXITCODE -ne 0) { throw 'Backend build failed' }
}
$worker = Start-Process -FilePath $python -ArgumentList '-m','uvicorn','worker.app:app','--host','127.0.0.1','--port','8090' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\.runtime\worker.log" -RedirectStandardError "$projectRoot\.runtime\worker-error.log" -PassThru
$java = (Get-Command java).Source
$backend = Start-Process -FilePath $java -ArgumentList '-Dfile.encoding=UTF-8','-jar',('"'+$jar+'"') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\.runtime\backend.log" -RedirectStandardError "$projectRoot\.runtime\backend-error.log" -PassThru
@{ worker=$worker.Id; backend=$backend.Id; root=$projectRoot } | ConvertTo-Json | Set-Content -LiteralPath '.runtime\pids.json' -Encoding UTF8
$url = "http://127.0.0.1:$($env:PORT)"
$ready = $false
for ($attempt=0; $attempt -lt 90; $attempt++) {
    try { $health=Invoke-RestMethod "$url/api/health" -TimeoutSec 2; if ($health.worker.status -eq 'ok') { $ready=$true; break } } catch {}
    if ($worker.HasExited -or $backend.HasExited) { break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'Services are not ready. Inspect .runtime/*error.log and backend.log. Use scripts/stop.ps1 before retrying.' }
Write-Host "MedAtlas ready: $url"
Write-Host "LLM configured: $($health.llmConfigured)"
Write-Host 'Only public/synthetic data should be used. Model mode is explicit in the UI.'
if (-not $NoBrowser) { Start-Process $url }
