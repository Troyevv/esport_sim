# Run exclusively on a disposable CI machine. Only the downloaded ZIP is launched.
param([Parameter(Mandatory)][string]$Archive, [switch]$CleanCore, [switch]$DesktopBrowser, [switch]$BrowserOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'tournament.ps1')
if ($CleanCore.IsPresent -eq $DesktopBrowser.IsPresent) { throw 'Choose exactly one Windows test environment.' }

function Wait-Check([string]$Description, [scriptblock]$Check, [int]$Seconds=60) {
    $until = [DateTime]::UtcNow.AddSeconds($Seconds)
    $lastError = ''
    do {
        try { if (& $Check) { return } } catch { $lastError = $_.Exception.Message }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $until)
    $launcherLog = Join-Path $env:LOCALAPPDATA 'EsportSim\launcher.log'
    Write-Warning ("Descriptor={0}, protocol handoffs={1}, profile={2}" -f (Test-Path $instancePath), @(Urls).Count, $env:LOCALAPPDATA)
    if (Test-Path $launcherLog) {
        Get-Content -Tail 30 -LiteralPath $launcherLog | Where-Object { $_ -notmatch '(?i)token|nonce|cookie|private key|code=' } | Write-Warning
    }
    Get-Process EsportSim,msedge,chrome -ErrorAction SilentlyContinue | ForEach-Object { Write-Warning "$($_.ProcessName) pid=$($_.Id)" }
    Get-WinEvent -FilterHashtable @{LogName='Application'; Level=2; StartTime=(Get-Date).AddMinutes(-5)} -MaxEvents 5 -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Warning ("Windows event {0}/{1}" -f $_.ProviderName, $_.Id) }
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
    Wait-Check 'server readiness descriptor' {
        if ($process.HasExited -and $process.ExitCode -ne 0) {
            throw "Launcher exited with $($process.ExitCode)"
        }
        Test-Path $instancePath
    }
    $instance = Read-Instance
    Write-Output "Ready on loopback port $($instance.port), pid=$($instance.pid)" | Out-Host
    Wait-Check 'fresh browser URL handoff from packaged EXE' { @(Urls).Count -eq ($previous + 1) }
    $origin = "http://127.0.0.1:$($instance.port)"
    if ((@(Urls)[-1]).TrimEnd('/') -ne $origin) { throw 'Opened URL differs from running server.' }
    $index = Invoke-WebRequest -UseBasicParsing -Uri "$origin/" -TimeoutSec 8
    $script = [regex]::Match($index.Content, 'src="(/assets/[^"]+\.js)"')
    if (-not $script.Success) { throw 'Frontend entry module unavailable.' }
    $asset = Invoke-WebRequest -UseBasicParsing -Uri ($origin + $script.Groups[1].Value) -TimeoutSec 8
    if ($asset.RawContentLength -lt 1) { throw 'Bundled frontend asset is empty.' }
    if ($DesktopBrowser) {
        $target = Get-Content -LiteralPath $env:ESPORT_SMOKE_TARGET -Raw | ConvertFrom-Json
        $portFile = Join-Path $target.profile 'DevToolsActivePort'
        Wait-Check 'Chromium debugger port file' { Test-Path -LiteralPath $portFile }
        $debugPort = (Get-Content -LiteralPath $portFile)[0]
        Wait-Check "Chromium loaded game on $origin" {
            $tabs = Invoke-RestMethod "http://127.0.0.1:$debugPort/json/list" -TimeoutSec 3
            @($tabs | Where-Object { $_.type -eq 'page' -and $_.url.TrimEnd('/') -eq $origin -and $_.title -match 'esport_sim' }).Count -ge 1
        }
        $null = taskkill /T /F /PID $target.pid
    }
    return $instance
}

function Command([string]$Origin, [string]$Kind, $Value = $null) {
    $state = Invoke-RestMethod "$Origin/api/state"
    $body = @{ id = [guid]::NewGuid().ToString(); context = $state.context; revision = $state.revision; kind = $Kind }
    if ($null -ne $Value) { $body.value = $Value }
    $null = Invoke-RestMethod "$Origin/api/command" -Method Post -Headers @{Origin=$Origin} -ContentType 'application/json' -Body ($body | ConvertTo-Json -Compress)
}

function Test-Lan([string]$Origin) {
    $headers = @{Origin=$Origin}
    $settings = Invoke-RestMethod "$Origin/api/host"
    if ($settings.enabled -or @($settings.addresses).Count -lt 1) {
        throw 'Expected disabled LAN with an eligible private Windows interface.'
    }
    $body = @{enabled=$true; address=$settings.addresses[0]} | ConvertTo-Json -Compress
    $settings = Invoke-RestMethod "$Origin/api/host/lan" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
    try {
        $lan = $settings.url
        if (!$settings.enabled -or !$lan.StartsWith('https://')) { throw 'LAN URL unavailable' }
        $qr = Invoke-WebRequest "$Origin/api/host/qr.svg" -UseBasicParsing
        $svg = if ($qr.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($qr.Content) } else { $qr.Content }
        if ($svg -notmatch '<svg' -or $svg -notmatch '<path') { throw 'QR rendering failed' }

        $authority = Join-Path $testRoot 'home.cer'
        Invoke-WebRequest "$Origin/api/host/authority.cer" -UseBasicParsing -OutFile $authority
        $fingerprint = (Get-FileHash $authority -Algorithm SHA256).Hash
        if ($fingerprint -ne $settings.fingerprint.Replace(':', '')) { throw 'Authority fingerprint mismatch' }

        Add-Type -AssemblyName System.Net.Http
        $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($authority)
        $store = [Security.Cryptography.X509Certificates.X509Store]::new('Root', 'LocalMachine')
        $store.Open('ReadWrite')
        $probeHandler = [Net.Http.HttpClientHandler]::new()
        $probeHandler.UseProxy = $false
        $probe = [Net.Http.HttpClient]::new($probeHandler)
        $imported = $false
        try {
            $untrusted = $false
            try {
                $null = $probe.GetAsync("$lan/api/capabilities").GetAwaiter().GetResult()
            } catch {
                $cause = $_.Exception
                while ($null -ne $cause) {
                    if (($cause -is [Net.WebException] -and $cause.Status -eq 'TrustFailure') -or
                        $cause -is [Security.Authentication.AuthenticationException]) { $untrusted = $true }
                    $cause = $cause.InnerException
                }
                if (-not $untrusted) { throw }
            }
            if (-not $untrusted) { throw 'Fresh authority was trusted before explicit import.' }
            # This is a disposable GitHub-hosted Windows VM. Exercise normal Windows
            # trust exactly as a client would, then remove only our new certificate.
            $store.Add($certificate)
            $imported = $true
            $test = Join-Path $PSScriptRoot 'trusted-lan.ps1'
            & $psExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $test -Lan $lan -Origin $Origin
            if ($LASTEXITCODE) { throw "Trusted HTTPS client exited with $LASTEXITCODE" }
        } catch {
            $reason = $_.Exception
            while ($null -ne $reason) {
                Write-Warning ("TLS diagnostic: {0}: {1}" -f $reason.GetType().Name, $reason.Message)
                $reason = $reason.InnerException
            }
            throw
        } finally {
            $probe.Dispose()
            if ($imported) { $store.Remove($certificate) }
            $store.Close()
        }
    } finally {
        $settings = Invoke-RestMethod "$Origin/api/host/lan" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"enabled":false}'
        if ($settings.enabled) { throw 'LAN failed to shut down.' }
    }
    Write-Output 'Packaged LAN adapter selection, QR, CA fingerprint, explicit TLS trust and client pairing verified.'
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
    if ((Get-ItemPropertyValue 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -Name InstallationType) -ne 'Server Core') {
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
    $env:ESPORT_SMOKE_PROFILE = Join-Path $testRoot 'browser-profiles'
    $env:ESPORT_SMOKE_TARGET = Join-Path $testRoot 'last-browser.json'
}

# Redirect the ephemeral account's HTTP association. Preserve the OS ShellExecute
# path used by a normal desktop double-click, including URL quoting.
$handler = Join-Path $PSScriptRoot 'open-url.ps1'
$psExe = Join-Path $PSHOME 'powershell.exe'
if (!(Test-Path $psExe)) { $psExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" }
$fixture = Join-Path $testRoot 'http-association.json'
@{urls=$env:ESPORT_SMOKE_URLS; target=$env:ESPORT_SMOKE_TARGET; browser=$env:ESPORT_SMOKE_BROWSER; profiles=$env:ESPORT_SMOKE_PROFILE} |
    ConvertTo-Json -Compress | Set-Content -LiteralPath $fixture
$openCommand = '"{0}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{1}" -Fixture "{2}" -Url "%1"' -f $psExe,$handler,$fixture
$choice = Get-ItemPropertyValue 'HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice' -Name ProgId -ErrorAction SilentlyContinue
if ($CleanCore) {
    # Stock Server Core has no desktop URL broker. Register a lightweight URL
    # recipient with the same App Paths contract as a locally installed browser.
    $probeExe = Join-Path $testRoot 'BrowserProbe.exe'
    Add-Type -Path (Join-Path $PSScriptRoot 'BrowserProbe.cs') -OutputAssembly $probeExe -OutputType ConsoleApplication
    $appPaths = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe')
    $appPaths.SetValue('', $probeExe)
    $appPaths.Dispose()
} else {
    foreach ($class in @('http', $choice) | Where-Object { $_ } | Select-Object -Unique) {
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Software\Classes\$class")
        $key.SetValue('URL Protocol','')
        $key.CreateSubKey('shell').SetValue('', 'open')
        $open = $key.CreateSubKey('shell\open\command')
        $open.SetValue('', $openCommand)
        $open.SetValue('DelegateExecute','')
        $open.Dispose()
        $key.Dispose()
    }
}

$instancePath = Join-Path $env:LOCALAPPDATA 'EsportSim\instance.json'
if (Test-Path $instancePath) { throw 'Existing launcher state found in fresh Windows environment.' }
$install = Join-Path $testRoot 'first install'
Expand-Archive -LiteralPath $Archive -DestinationPath $install
$exe = Join-Path $install 'EsportSim\EsportSim.exe'
$nativeReport = Join-Path $testRoot 'native-query.json'
$native = Start-Process -FilePath $exe -ArgumentList "--verify-native `"$nativeReport`"" -PassThru
if (!$native.WaitForExit(60000)) { $native.Kill(); throw 'Native geometry check timed out' }
if ($native.ExitCode -ne 0) { throw (Get-Content -Raw -LiteralPath $nativeReport) }
$hit = Get-Content -Raw -LiteralPath $nativeReport | ConvertFrom-Json
if ($hit.face -ne 0 -or [Math]::Abs($hit.distance - 2.0) -gt 1e-6) { throw 'Packaged native geometry returned an incorrect hit' }
$first = Launch-Archive $exe
if ($first.port -ne 8765) { throw "Unexpected default port $($first.port)" }
$again = Launch-Archive $exe
if ($again.pid -ne $first.pid -or $again.port -ne $first.port -or $again.nonce -ne $first.nonce) { throw 'Second launch did not reuse the same instance.' }
Wait-Check 'secondary launcher exit' { @(Get-Process -Name EsportSim -ErrorAction SilentlyContinue).Count -eq 1 }
$origin = "http://127.0.0.1:$($first.port)"
if ($DesktopBrowser) {
    Test-Lan $origin
    if ($BrowserOnly) {
        Stop-HostInstance $first
        return
    }
}
if (!(Test-Path (Join-Path $install 'EsportSim\TACTICS.md'))) { throw 'Tactics guide missing from archive.' }
$personal = Invoke-RestMethod "$origin/api/database/personal-badges/status"
if ($personal.mode -ne 'off' -or $personal.available -lt 167 -or $personal.ready -ne 0) { throw 'Packaged private logo catalog is missing or contains private files.' }
$scene = (Invoke-RestMethod "$origin/api/database/scene-20261125-staff/1").package
$portraits = Invoke-RestMethod "$origin/api/portraits/scene-20261125-staff/1/index"
$people = @($scene.players.PSObject.Properties.Name) + @($scene.staff.PSObject.Properties.Name)
if ($people.Count -ne $portraits.PSObject.Properties.Name.Count) { throw 'Packaged portrait coverage is incomplete.' }
foreach ($id in $people) {
    $head = $portraits.PSObject.Properties[$id].Value
    if (!$head.synthetic -or $head.image -notmatch '^/api/portraits/generated/[0-9a-f]{64}$') {
        throw "Missing generated appearance or unexpected private art for $id."
    }
}
$sample = Invoke-WebRequest -UseBasicParsing -Uri ($origin + $head.image)
if ($sample.Headers['Content-Type'] -notmatch 'image/webp' -or $sample.RawContentLength -lt 200) { throw 'Offline face bytes unavailable.' }
if (!(Test-Path (Join-Path $install 'EsportSim\STAFF_R51.md'))) { throw 'Staff guide missing from archive.' }
if ($scene.players.PSObject.Properties.Name.Count -lt 1500) { throw 'Offline player database missing from Windows distribution.' }
$lineups = @($scene.rosters.PSObject.Properties | Where-Object { $_.Value.name -in @('Team Vitality','Team Falcons') } | ForEach-Object { $_.Name })
if (!(Test-Path (Join-Path $install 'EsportSim\CAREER_R33.md'))) { throw 'Career guide missing.' }
$starter = Invoke-RestMethod "$origin/api/career/options/austin-registration/1"
Command $origin 'career-create' @{id='austin-registration'; revision=1; team=($starter.teams | Where-Object { $_.region -eq 'Asia' } | Select-Object -First 1).id; mode='owner'; scope='fast'; regions=@('Asia'); name='Manager'}
Command $origin 'career-save' @{slot='2'}
Command $origin 'career-advance'
Wait-Check 'packaged career stops before user match' {
    $c = (Invoke-RestMethod "$origin/api/career").active
    if ($c.error) { Write-Warning $c.error; throw $c.error }
    $c.date -gt $c.start -and !$c.progress -and $c.history.Count -gt 0
} 240
Command $origin 'career-play'
$careerState = (Invoke-RestMethod "$origin/api/state")
if (!$careerState.careerId -or $careerState.world.series.stage -ne 'veto' -or $careerState.world.series.bestOf -ne 3) { throw 'Career BO3 veto missing.' }
Command $origin 'series-veto' @{delegate='captain'}
Command $origin 'series-next'
$careerMap = (Invoke-RestMethod "$origin/api/state").world
if ($careerMap.match.teams.Count -ne 2 -or $careerMap.series.order.Count -ne 3 -or $careerMap.map.id -ne $careerMap.series.order[0].map) { throw 'Packaged BO3 did not open the selected first map.' }
Command $origin 'career-load' @{slot='2'}
$c = (Invoke-RestMethod "$origin/api/career").active
if ($c.date -ne $c.start -or $c.history.Count -ne 0 -or $c.roster.Count -ne 5) { throw 'Career slot did not restore.' }
Command $origin 'career-lab'
$maps = Invoke-RestMethod "$origin/api/maps"
$installed = @($maps | ForEach-Object { $_.id } | Sort-Object)
$expected = @('de_ancient', 'de_anubis', 'de_cache', 'de_dust2', 'de_inferno', 'de_mirage', 'de_nuke', 'de_train', 'de_vertigo', 'depo')
if (Compare-Object $expected $installed) { throw "Unexpected packaged map catalog: $($installed -join ', ')" }
Command $origin 'database-match' @{id=$scene.id;revision=1;seed=42;rosters=$lineups;map='de_nuke'}
$realMatch = (Invoke-RestMethod "$origin/api/state").world.match
if ($realMatch.source.id -ne $scene.id -or 'Team Vitality' -notin $realMatch.teams) { throw 'Packaged real BO1 did not load.' }
if ((Invoke-RestMethod "$origin/api/state").world.map.id -ne 'de_nuke') { throw 'Wrong BO1 map.' }
Command $origin 'speed' 8
Command $origin 'start'
Wait-Check 'native live ticks on Nuke' {
    $world = (Invoke-RestMethod "$origin/api/state").world
    $world.match.phase -eq 'live' -and $world.tick -ge 90
}
Command $origin 'pause'
Command $origin 'save'
Command $origin 'load'
if ((Invoke-RestMethod "$origin/api/state").world.map.id -ne 'de_nuke') { throw 'Map lost after save/load.' }
$library = Invoke-RestMethod "$origin/api/tactics"
$plan = $library.plans | Where-Object { $_.id -eq 'std-T-0' }
if ($plan.slots.Count -ne 5) { throw 'Packaged board has no five-slot plan.' }
Command $origin 'match' 705177
$projection = (Invoke-RestMethod "$origin/api/state").world
if ($projection.match.rules -ne 'depo-bo1.4' -or $null -eq $projection.match.teamRating -or
    $projection.match.roleRatings.T1.PSObject.Properties.Name.Count -ne 6 -or $projection.domain) {
    throw 'R3.1 match projection is missing or exposes the private world.'
}
if (@($projection.agents | Where-Object { $_.secondary -in @('Glock', 'USP') -and !$_.primary }).Count -ne 10) {
    throw 'Starting BO1 loadouts do not contain ten secondary weapons.'
}
foreach ($icon in @('ak47', 'm4a1_silencer', 'awp', 'deagle', 'flashbang', 'c4', 'icon_headshot')) {
    $asset = Invoke-WebRequest -UseBasicParsing -Uri "$origin/scorebot/$icon.svg" -TimeoutSec 8
    if ($asset.Headers['Content-Type'] -notmatch 'image/svg\+xml' -or $asset.RawContentLength -lt 50) {
        throw "Packaged Scorebot icon missing: $icon"
    }
}
Command $origin 'tactic-assign' @{id=$plan.id; revision=$plan.revision}
Command $origin 'timeout'
Command $origin 'resume'
Command $origin 'speed' 128
Wait-Check 'packaged BO1 reaches a final score' {
    $world = (Invoke-RestMethod "$origin/api/state").world
    $world.match.phase -eq 'finished' -and $world.match.remaining -eq 2 -and
        ($world.match.score[0] + $world.match.score[1]) -eq $world.match.history.Count
}
$world = (Invoke-RestMethod "$origin/api/state").world
foreach ($club in $world.match.clubs) {
    $wins = @($world.match.history | Where-Object { $_.winnerTeamId -eq $club.id }).Count
    if ($club.score -ne $wins) { throw "Packaged BO1 standings do not match the round ledger." }
}
if ($world.match.winnerTeamId -ne $world.match.history[-1].winnerTeamId) { throw 'BO1 winner mismatch.' }
if ($world.match.history[0].tactic.id -ne $plan.id) { throw 'BO1 did not execute the packaged board.' }
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
    $restored = (Invoke-RestMethod "$origin/api/state").world
    if ($restored.seed -ne 705177 -or $restored.match.phase -ne 'finished') { throw 'Saved BO1 lost after restart.' }
    Stop-HostInstance $other
} finally { $occupied.Stop() }
$last = Launch-Archive $exe
if ($last.port -ne 8765) { throw 'Default port not reclaimed after shutdown.' }
Test-AuroraTournament "http://127.0.0.1:$($last.port)"
Stop-HostInstance $last
Write-Output 'Verified occupied port, durable save across extractions, released port and final relaunch.'
