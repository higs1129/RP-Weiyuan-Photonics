$ErrorActionPreference='Stop'
$env:PSModulePath="$PSHOME\Modules;"+$env:PSModulePath
. (Join-Path $PSScriptRoot 'home.ps1')
$appRoot=Resolve-RpWeiyuanHome
try {
    $state=Get-Content -LiteralPath (Join-Path $appRoot 'current.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $python=Join-Path $state.env 'Scripts\python.exe'
    & $python -I -X utf8 (Join-Path $PSScriptRoot 'network_diagnose.py') @args
    exit $LASTEXITCODE
} catch {
    Write-Host ('ERROR: '+$_.Exception.Message) -ForegroundColor Red
    exit 1
}
