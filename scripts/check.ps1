$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8='1'
$env:JAVA_TOOL_OPTIONS='-Dfile.encoding=UTF-8'
& .\.venv\Scripts\python.exe -m pytest worker\tests -q
if($LASTEXITCODE -ne 0){throw 'Python tests failed'}
& mvn -f backend\pom.xml "-Dmaven.repo.local=$projectRoot\.runtime\m2" -B -ntp test
if($LASTEXITCODE -ne 0){throw 'Java tests failed'}
& .\.venv\Scripts\python.exe scripts\smoke_test.py
if($LASTEXITCODE -ne 0){throw 'HTTP smoke test failed (start services first)'}
