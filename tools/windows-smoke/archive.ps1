# Run exclusively on a disposable CI machine. Only the downloaded ZIP is launched.
param([Parameter(Mandatory)][string]$Archive, [switch]$CleanCore, [switch]$DesktopBrowser)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($CleanCore -eq $DesktopBrowser) { throw 'Choose exactly one Windows test environment.' }

function Wait-Check([string]$Description, [scriptblock]$Check) {
    $until = [DateTime]::UtcNow.AddSeconds(60)
    $lastError = ''
    do {
        try { if (& $Check) { return } } catch { $lastError = $_.Exception.Message }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $until)
    throw "Timed out: $Description. $lastError"
}

function Read-Instance {
    Get-Content -Raw -LiteralPath $instancePath | ConvertFrom-Json
}

function Urls {
    if (Test-Path -LiteralPath $env:ESPORT_SMOKE_URLS) {
        Get-Content -LiteralPath $env:ESPORT_SMOKE_URLS
    }
}

function Assert-FreePort([int]$Port) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() } finally { $listener.Stop() }
}

function Launch-Archive([string]$Exe) {
    $previous = @(Urls).Count
    $process = Start-Process -FilePath $Exe -PassThru
    Wait-Check 'server readiness file and browser handoff' {
        if ($process.HasExited -and $process.ExitCode -ne 0) {
            throw "Launcher exited with $($process.ExitCode)"
        }
        (Test-Path $instancePath) -and (@(Urls).Count -eq ($previous + 1))
    }
    $instance = Read-Instance
    $origin = "http://127.0.0.1:$($instance.port)"
    if ((@(Urls)[-1]).TrimEnd('/') -ne $origin) { throw 'Opened URL differs from running server.' }
    $index = Invoke-WebRequest -UseBasicParsing -Uri "$origin/" -TimeoutSec 8
    $script = [regex]::Match($index.Content, 'src="(/assets/[^"]+\.js)"')
    if (-not $script.Success) { throw 'Frontend entry module unavailable.' }
    $asset = Invoke-WebRequest -UseBasicParsing -Uri ($origin + $script.Groups[1].Value) -TimeoutSec 8
    if ($asset.RawContentLength -lt 1) { throw 'Bundled frontend asset is empty.' }
    if ($DesktopBrowser) {
        Wait-Check 'Chromium opened the requested game tab' {
            $tabs = Invoke-RestMethod 'http://127.0.0.1:9227/json/list' -TimeoutSec 3
            @($tabs | Where-Object { $_.type -eq 'page' -and $_.url.TrimEnd('/') -eq $origin -and $_.title -match 'esport_sim' }).Count -ge 1
        }
    }
    return $instance
}

function Command([string]$Origin, [string]$Kind, $Value = $null) {
    $state = Invoke-RestMethod "$Origin/api/state"
    $body = @{ id = [guid]::NewGuid().ToString(); context = $state.context; revision = $state.revision; kind = $Kind }
    if ($null -ne $Value) { $body.value = $Value }
    $null = Invoke-RestMethod "$Origin/api/command" -Method Post -Headers @{Origin=$Origin} -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress)
}

function Stop-HostInstance($Instance) {
    $origin = "http://127.0.0.1:$($Instance.port)"
    $null = Invoke-RestMethod "$origin/api/host/shutdown" -Method Post -Headers @{Origin=$origin}
    Wait-Check 'server process exit and readiness-file removal' {
        (-not (Get-Process -Id $Instance.pid -ErrorAction SilentlyContinue)) -and (-not (Test-Path $instancePath))
    }
    Assert-FreePort $Instance.port
}

if ($CleanCore) {
    foreach ($name in @('py.exe','python.exe','python3.exe','node.exe','npm.cmd','git.exe')) {
        if (Get-Command $name -ErrorAction SilentlyContinue) { throw "$name installed on clean image" }
    }
    if ((Get-ComputerInfo -Property WindowsInstallationType).WindowsInstallationType -ne 'Server Core') {
        throw 'Expected Windows Server Core'
    }
    Write-Output 'Pristine Server Core image verified. Python, Node.js, npm and Git are absent.'
}
$testRoot = Join-Path $env:TEMP ('Esport Sim smoke ' + [guid]::NewGuid())
$null = New-Item -ItemType Directory $testRoot
$env:ESPORT_SMOKE_URLS = Join-Path $testRoot 'opened.txt'
if ($DesktopBrowser) {
    $env:ESPORT_SMOKE_BROWSER = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $env:ESPORT_SMOKE_BROWSER) { throw 'Windows test browser unavailable.' }
    $env:ESPORT_SMOKE_PROFILE = Join-Path $testRoot 'browser-profile'
}

# Redirect the ephemeral account's HTTP association. Preserve the OS ShellExecute
# path used by a normal desktop double-click, including URL quoting.
$handler = Join-Path $PSScriptRoot 'open-url.ps1'
$psExe = Join-Path $PSHOME 'powershell.exe'
if (!(Test-Path $psExe)) { $psExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" }
$openCommand = '"{0}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{1}" "%1"' -f $psExe,$handler
$choice = Get-ItemPropertyValue 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice' -Name ProgId -ErrorAction SilentlyContinue
foreach ($class in @('http', $choice) | Where-Object { $_ } | Select-Object -Unique) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Software\Classes\$class")
    $key.SetValue('URL Protocol','')
    $open = $key.CreateSubKey('shell\open\command')
    $open.SetValue('', $openCommand)
    $open.SetValue('DelegateExecute','')
    $open.Dispose()
    $key.Dispose()
}

$instancePath = Join-Path $env:LOCALAPPDATA 'EsportSim\instance.json'
if (Test-Path $instancePath) { throw 'Existing launcher state found in fresh Windows environment.' }
$install = Join-Path $testRoot 'first install'
Expand-Archive -LiteralPath $Archive -DestinationPath $install
$exe = Join-Path $install 'EsportSim\EsportSim.exe'
$first = Launch-Archive $exe
if ($first.port -ne 8765) { throw "Unexpected default port $($first.port)" }
$again = Launch-Archive $exe
if ($again.pid -ne $first.pid -or $again.port -ne $first.port -or $again.nonce -ne $first.nonce) { throw 'Second launch did not reuse the same instance.' }
Wait-Check 'secondary launcher exit' { @(Get-Process -Name EsportSim -ErrorAction SilentlyContinue).Count -eq 1 }
$origin = "http://127.0.0.1:$($first.port)"
Command $origin 'reset' 705177
Command $origin 'save'
Command $origin 'reset' 47
Stop-HostInstance $first
Write-Output 'Initial run, browser handoff, second launch, persistence and shutdown verified.'

$occupied = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 8765)
try {
    $occupied.Start()
    # New extraction detects data accidentally stored beside the executable.
    $secondInstall = Join-Path $testRoot 'fresh extraction'
    Expand-Archive -LiteralPath $Archive -DestinationPath $secondInstall
    $other = Launch-Archive (Join-Path $secondInstall 'EsportSim\EsportSim.exe')
    if ($other.port -eq 8765) { throw 'Occupied port was not handled.' }
    $origin = "http://127.0.0.1:$($other.port)"
    $state = Invoke-RestMethod "$origin/api/state"
    if (-not $state.hasSave -or $state.world.seed -ne 47) { throw 'Persisted state lost after restart.' }
    Command $origin 'load'
    if ((Invoke-RestMethod "$origin/api/state").world.seed -ne 705177) { throw 'Saved snapshot lost after restart.' }
    Stop-HostInstance $other
} finally { $occupied.Stop() }
$last = Launch-Archive $exe
if ($last.port -ne 8765) { throw 'Default port not reclaimed after shutdown.' }
Stop-HostInstance $last
Write-Output 'Verified occupied port, durable save across extractions, released port and final relaunch.'
