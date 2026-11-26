# Exercise the user's BAT entry points in a fresh checkout with a Unicode path.
param([Parameter(Mandatory)][string]$PackagedExe)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tournament.ps1')
$sample = (Resolve-Path 'tests/portrait_samples/studio-1.jpg').Path
$head = Join-Path $env:TEMP 'esportsim-portrait-smoke.png'
$ml = Start-Process -FilePath $PackagedExe -ArgumentList "--prepare-head `"$sample`" `"$head`"" -PassThru
if (-not $ml.WaitForExit(120000)) { $ml.Kill(); throw 'Packaged portrait processor timed out.' }
if (Test-Path "$head.error.txt") { Get-Content "$head.error.txt" }
if ($ml.ExitCode -ne 0 -or -not (Test-Path $head) -or (Get-Item $head).Length -lt 1000) { throw 'Packaged local portrait processor failed.' }
$exe = (Resolve-Path $PackagedExe).Path
$checkout = Join-Path $env:RUNNER_TEMP 'Исходники Esport Sim'
$archive = Join-Path $env:RUNNER_TEMP 'source.zip'
git archive --format=zip --output=$archive HEAD
if ($LASTEXITCODE) { throw 'Cannot export source tree' }
Expand-Archive -LiteralPath $archive -DestinationPath $checkout
Push-Location $checkout
function Instance { Get-Content -Raw -LiteralPath $descriptor | ConvertFrom-Json }
function Batch($name) {
    & cmd.exe /d /c "$name.bat <nul"
    if ($LASTEXITCODE) { throw "$name.bat exited with $LASTEXITCODE" }
}
function Stamps {
    foreach ($path in '.venv/.esportsim-dependencies','frontend/node_modules/.esportsim-dependencies','build/source-launcher/frontend.sha256') {
        (Get-Item -LiteralPath $path).LastWriteTimeUtc.Ticks
    }
}
function Stop-Game {
    Batch 'stop'
    if (Test-Path $descriptor) { throw 'Launcher did not shut down' }
}
$other = Start-Process python -ArgumentList '-c "import time; time.sleep(600)"' -PassThru
# Import a real interrupted game from the first commit of PR #3 into a fresh home.
$env:LOCALAPPDATA = Join-Path $env:RUNNER_TEMP 'BAT profile'
$descriptor = Join-Path $env:LOCALAPPDATA 'EsportSim\instance.json'
$null = New-Item -ItemType Directory -Force (Join-Path $env:LOCALAPPDATA 'EsportSim')
$save = Join-Path $env:LOCALAPPDATA 'EsportSim\scenario.sqlite'
python -c "import gzip,sys,pathlib; pathlib.Path(sys.argv[1]).write_bytes(gzip.decompress(pathlib.Path('tests/fixtures/bo1-67e384f.sqlite.gz').read_bytes()))" $save
if ($LASTEXITCODE) { throw 'Cannot restore legacy profile fixture' }
$occupied = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8765)
try {
    $occupied.Start()
    $env:ESPORT_SIM_MAPS = Join-Path $env:RUNNER_TEMP 'removed old maps folder'
    Batch 'start'
    $initial = Instance
    $before = @(Stamps)
    $origin = "http://127.0.0.1:$($initial.port)"
    if ($initial.port -eq 8765) { throw 'Expected fallback port' }
    node frontend/e2e/windows-launch.mjs $origin
    if ($LASTEXITCODE) { throw 'BAT browser regression failed' }
    $state = Invoke-RestMethod "$origin/api/state"
    $body = @{id=[guid]::NewGuid().ToString();context=$state.context;revision=$state.revision;kind='save'} | ConvertTo-Json
    $null = Invoke-RestMethod "$origin/api/command" -Method Post -Headers @{Origin=$origin} -ContentType 'application/json' -Body $body
    Batch 'start'
    if ((Instance).nonce -ne $initial.nonce) { throw 'Repeat BAT launch replaced the server' }
    $secondary = Start-Process $exe -PassThru
    if (!$secondary.WaitForExit(20000) -or (Instance).nonce -ne $initial.nonce) { throw 'EXE did not reuse the BAT instance' }
    Stop-Game
    Batch 'start'
    if (Compare-Object $before @(Stamps)) { throw 'Unchanged checkout repeated preparation' }
    Stop-Game
    Add-Content frontend/src/radar.css '/* acceptance */'
    Batch 'start'
    $changed = @(Stamps)
    if ($changed[0] -ne $before[0] -or $changed[1] -ne $before[1] -or $changed[2] -eq $before[2]) { throw 'Frontend invalidation was not selective' }
    Stop-Game
    Add-Content requirements.txt '# acceptance'
    Add-Content frontend/package-lock.json ' '
    Batch 'start'
    $updated = @(Stamps)
    foreach ($i in 0..2) { if ($changed[$i] -eq $updated[$i]) { throw "Lockfile change missed at step $i" } }
    Stop-Game
    $ownerProcess = Start-Process $exe -PassThru
    $limit = [DateTime]::UtcNow.AddSeconds(30)
    while (!(Test-Path $descriptor) -and [DateTime]::UtcNow -lt $limit) { Start-Sleep -Milliseconds 100 }
    $owner = Instance
    $state = Invoke-RestMethod "http://127.0.0.1:$($owner.port)/api/state"
    if (!$state.hasSave -or $state.context -ne ($body | ConvertFrom-Json).context) { throw 'EXE did not recover the source save' }
    Batch 'start'
    if ((Instance).pid -ne $owner.pid) { throw 'BAT did not reuse the running EXE' }
    Stop-Game
    $cache = Join-Path $env:LOCALAPPDATA 'EsportSim/maps/26879581/de_nuke/collision.json'
    [IO.File]::WriteAllText($cache,'damaged')
    Batch 'start'
    $fresh = Instance
    Test-AuroraTournament "http://127.0.0.1:$($fresh.port)"
    Stop-Game
    Batch 'stop'
    if ($other.HasExited) { throw 'Unrelated Python process was terminated' }
    Write-Output 'BAT cold start, cached restart, source and lockfile changes, shared EXE state and targeted shutdown passed.'
} finally {
    $occupied.Stop()
    $log = Join-Path $env:LOCALAPPDATA 'EsportSim\launcher.log'
    if (Test-Path $log) { Get-Content -LiteralPath $log -Tail 24 }
    if (Test-Path $descriptor) { Batch 'stop' }
    if (!$other.HasExited) { $other.Kill() }
    Pop-Location
}
