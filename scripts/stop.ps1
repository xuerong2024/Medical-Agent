$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pidFile=Join-Path $projectRoot '.runtime\pids.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No project process record.'; exit }
$record=Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.root -ne $projectRoot) { throw 'Process record belongs to a different directory.' }
foreach ($role in @('backend','worker')) {
    $processId=[int]$record.$role
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $expected=if ($role -eq 'backend') { 'backend\target\medical-agent-0.1.0.jar' } else { '.venv\Scripts\python.exe' }
    $identity=if ($role -eq 'backend') { $process.CommandLine } else { $process.ExecutablePath }
    if (-not $identity -or -not $identity.Contains((Join-Path $projectRoot $expected))) { throw "PID $processId does not match this project. Refusing to stop it." }
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
    Write-Host "Stopped project $role ($processId)."
}
# Keep files and process record for audit. Nothing is deleted.
if (Test-Path -LiteralPath (Join-Path $projectRoot 'data\postgres-local\PG_VERSION')) {
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') (Join-Path $projectRoot 'scripts\local_postgres.py') stop
    Write-Host 'Stopped project PostgreSQL.'
}
