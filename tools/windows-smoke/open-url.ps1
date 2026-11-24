# URL protocol handler used only on a disposable Windows test machine.
param([Parameter(Mandatory)][string]$Url)
$ErrorActionPreference = 'Stop'
if ($Url -notmatch '^http://127\.0\.0\.1:[0-9]+/?$') {
    throw "Unexpected browser handoff: $Url"
}
if ($env:ESPORT_SMOKE_BROWSER) {
    $arguments = @('--headless=new', '--no-first-run', '--disable-default-apps',
        '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--remote-debugging-port=9227', ('--user-data-dir="{0}"' -f $env:ESPORT_SMOKE_PROFILE), $Url)
    Start-Process -FilePath $env:ESPORT_SMOKE_BROWSER -ArgumentList $arguments
}
Add-Content -LiteralPath $env:ESPORT_SMOKE_URLS -Value $Url -Encoding UTF8
