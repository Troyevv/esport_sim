# URL protocol handler used only on a disposable Windows test machine.
param([Parameter(Mandatory)][string]$Url)
$ErrorActionPreference = 'Stop'
if ($Url -notmatch '^http://127\.0\.0\.1:[0-9]+/?$') {
    throw "Unexpected browser handoff: $Url"
}
if ($env:ESPORT_SMOKE_BROWSER) {
    $profile = Join-Path $env:ESPORT_SMOKE_PROFILE ([guid]::NewGuid().ToString())
    $null = New-Item -ItemType Directory -Force -Path $profile
    $arguments = @('--headless=new', '--no-first-run', '--disable-default-apps',
        '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--remote-debugging-port=0', ('--user-data-dir="{0}"' -f $profile), $Url)
    $browser = Start-Process -FilePath $env:ESPORT_SMOKE_BROWSER -ArgumentList $arguments -PassThru
    @{profile=$profile; pid=$browser.Id} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:ESPORT_SMOKE_TARGET
}
Add-Content -LiteralPath $env:ESPORT_SMOKE_URLS -Value $Url -Encoding UTF8
