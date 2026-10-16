param([ValidateSet('launch','setup','diagnose','repair','driver')][string]$Mode = 'launch')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# A terminal/IDE may prepend PowerShell 7 modules to a Windows PowerShell 5.1 child.
$env:PSModulePath = "$PSHOME\Modules;" + $env:PSModulePath
$projectRoot = Split-Path $PSScriptRoot -Parent
$bundleRoot = Join-Path $projectRoot 'dependencies'
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'config.json'))) {
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config.example.json') -Destination (Join-Path $projectRoot 'config.json')
}
. (Join-Path $PSScriptRoot 'home.ps1')
$appRoot = Resolve-RpWeiyuanHome
$Host.UI.RawUI.WindowTitle = 'RP*微源光子测控平台'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Check-Hash($file, $hash) {
    if (!(Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $hash) {
        throw "Package checksum failed: $file. Restore this resource from Git or the original download."
    }
}
function Compatible-Python($exe) {
    if (!$exe -or !(Test-Path -LiteralPath $exe -PathType Leaf)) { return $false }
    try {
        $probe = & $exe -I -c "import sys,struct; print('RP_WEIYUAN_OK' if sys.version_info[:2]==(3,10) and struct.calcsize('P')==8 else 'INCOMPATIBLE')" 2>$null
        return $LASTEXITCODE -eq 0 -and $probe -contains 'RP_WEIYUAN_OK'
    } catch { return $false }
}
try {
    if (![Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Windows x64 is required.' }
    $manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($asset in $manifest.files) {
        # Diagnostics use the installed snapshot without downloading resources.
        if ($Mode -eq 'diagnose' -or (Test-Path -LiteralPath (Join-Path $appRoot 'pending-update.json'))) { break }
        $file = Join-Path $bundleRoot $asset.path
        if (!(Test-Path -LiteralPath $file) -and $asset.url -and $config.installation.allow_downloads -ne $false) {
            Write-Host "Downloading missing asset: $($asset.path)"
            New-Item -ItemType Directory -Force (Split-Path $file -Parent) | Out-Null
            Invoke-WebRequest -UseBasicParsing -Uri $asset.url -OutFile "$file.part"
            Check-Hash "$file.part" $asset.sha256
            Move-Item -LiteralPath "$file.part" -Destination $file
        }
        Check-Hash $file $asset.sha256
    }
    if ($Mode -eq 'driver') {
        # Called only by install-con-driver.cmd. Windows owns the UAC consent UI.
        $driverPath = Join-Path $bundleRoot 'drivers\*.inf'
        $process = Start-Process -FilePath "$env:SystemRoot\System32\pnputil.exe" -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/add-driver', ('"' + $driverPath + '"'), '/subdirs', '/install')
        if ($process.ExitCode -notin @(0,3010)) { throw "Driver installation returned $($process.ExitCode)" }
        Write-Host 'FTDI CON driver installed. Reconnect the USB data cable.'
        exit 0
    }
    $candidates = [Collections.Generic.List[string]]::new()
    if ($config.installation.python_path) {
        if (!(Compatible-Python $config.installation.python_path)) { throw 'installation.python_path must point to a working Python 3.10 x64 python.exe.' }
        $candidates.Add($config.installation.python_path)
    }
    if (Test-Path -LiteralPath (Join-Path $appRoot 'current.json')) {
        $current = Get-Content -LiteralPath (Join-Path $appRoot 'current.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $candidates.Add((Join-Path $current.env 'Scripts\python.exe'))
    }
    $candidates.Add((Join-Path $appRoot 'python310\python.exe'))
    if ($env:A221_RUNTIME_PYTHON) { $candidates.Add($env:A221_RUNTIME_PYTHON) }
    $legacyEnvs = Join-Path $env:LOCALAPPDATA 'MicrocavityControl\envs'
    if (Test-Path -LiteralPath $legacyEnvs) {
        foreach ($oldEnv in Get-ChildItem -LiteralPath $legacyEnvs -Directory) {
            $candidates.Add((Join-Path $oldEnv.FullName 'Scripts\python.exe'))
        }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $found = & $py.Source -3.10 -I -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { $candidates.Add([string]($found | Select-Object -Last 1)) }
        } catch { Write-Host 'Python launcher has no usable Python 3.10; checking other locations.' }
    }
    foreach ($key in @('HKCU:\Software\Python\PythonCore\3.10\InstallPath','HKLM:\Software\Python\PythonCore\3.10\InstallPath')) {
        if (Test-Path $key) { $candidates.Add((Join-Path (Get-Item $key).GetValue('') 'python.exe')) }
    }
    foreach ($found in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($found.Source -notlike '*WindowsApps*') { $candidates.Add($found.Source) }
    }
    $python = $null
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Compatible-Python $candidate) { $python = $candidate; break }
    }
    if (!$python) {
        if ($Mode -eq 'diagnose') { throw 'No compatible Python 3.10 x64 found. Run setup.cmd first.' }
        New-Item -ItemType Directory -Force $appRoot | Out-Null
        $installer = Join-Path $bundleRoot 'runtime\python-3.10.11-amd64.exe'
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'Python installer signature verification failed.' }
        Write-Host 'Installing private Python 3.10.11; system PATH and file associations stay unchanged.'
        $targetDir = Join-Path $appRoot 'python310'
        $process = Start-Process -FilePath $installer -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/quiet', 'InstallAllUsers=0', ('TargetDir="' + $targetDir + '"'), 'Include_pip=1', 'Include_launcher=0', 'InstallLauncherAllUsers=0', 'PrependPath=0', 'AssociateFiles=0', 'Shortcuts=0', 'Include_test=0', 'Include_doc=0', 'Include_tcltk=0')
        if ($process.ExitCode -notin @(0,3010)) { throw "Python installation failed: $($process.ExitCode)" }
        $python = Join-Path $targetDir 'python.exe'
        if (!(Compatible-Python $python)) { throw 'Installed Python failed its startup check.' }
    }
    # Run the manager from the base interpreter, so it does not hold open an old
    # venv's python.exe while cleaning a successfully replaced environment.
    $baseCandidate = & $python -I -c "import sys; print(getattr(sys, '_base_executable', sys.executable))" 2>$null
    if ($LASTEXITCODE -eq 0 -and $baseCandidate) {
        $baseCandidate = [string]($baseCandidate | Select-Object -Last 1)
        if (Compatible-Python $baseCandidate) { $python = $baseCandidate }
    }
    Write-Host "Python: $python"
    & $python -I -X utf8 (Join-Path $PSScriptRoot 'manage.py') --project $projectRoot --home $appRoot --mode $Mode
    exit $LASTEXITCODE
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
