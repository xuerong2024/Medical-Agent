$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Force -Path '.runtime','data' | Out-Null
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { python -m venv .venv }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$env:PYTHONUTF8='1'
$env:PIP_CACHE_DIR=Join-Path $projectRoot '.runtime\pip-cache'
& $python -m pip install -r worker\requirements-rag.txt
if ($LASTEXITCODE -ne 0) { throw 'RAG dependencies failed' }
& $python scripts\install_embeddings.py
if ($LASTEXITCODE -ne 0) { throw 'Embedding model download failed' }
& $python scripts\local_postgres.py
if ($LASTEXITCODE -ne 0) { throw 'Project PostgreSQL setup failed' }
Write-Host 'Local RAG ready. Restart MedAtlas, then rebuild the vector index in the Knowledge menu.'
Write-Host 'Existing H2 data is preserved but is not migrated automatically. See README.'
