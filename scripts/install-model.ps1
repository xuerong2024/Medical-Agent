$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { python -m venv .venv }
$env:PIP_CACHE_DIR=Join-Path $projectRoot '.runtime\pip-cache'
$env:TOTALSEG_HOME_DIR=Join-Path $projectRoot 'data\worker\models'
& $python -m pip install --timeout 180 -r worker\requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Model dependency installation failed.' }
New-Item -ItemType Directory -Force -Path $env:TOTALSEG_HOME_DIR | Out-Null
& $python -c "import os,json; from pathlib import Path; from totalsegmentator.config import setup_totalseg; setup_totalseg(); p=Path(os.environ['TOTALSEG_HOME_DIR'])/'config.json'; c=json.loads(p.read_text()); c['send_usage_stats']=False; p.write_text(json.dumps(c)); from totalsegmentator.libs import download_pretrained_weights; download_pretrained_weights(297); download_pretrained_weights(298)"
if ($LASTEXITCODE -ne 0) { throw 'Public model weights download failed; retry when network is available.' }
Write-Host 'Public fast CT weights installed. Telemetry disabled. Full-resolution weights download on first use.'
