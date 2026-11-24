# URL protocol handler used only on a disposable Windows test machine.
param([Parameter(Mandatory)][string]$Fixture, [Parameter(Mandatory)][string]$Url)
$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath $Fixture | ConvertFrom-Json
if ($Url -notmatch '^http://127\.0\.0\.1:[0-9]+/?$') {
    throw "Unexpected browser handoff: $Url"
}
if ($config.browser) {
    $profile = Join-Path $config.profiles ([guid]::NewGuid().ToString())
    $null = New-Item -ItemType Directory -Force -Path $profile
    $arguments = @('--headless=new', '--no-first-run', '--disable-default-apps',
        '--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--remote-debugging-port=0', ('--user-data-dir="{0}"' -f $profile), $Url)
    $browser = Start-Process -FilePath $config.browser -ArgumentList $arguments -PassThru
    @{profile=$profile; pid=$browser.Id} | ConvertTo-Json -Compress | Set-Content -LiteralPath $config.target
}
Add-Content -LiteralPath $config.urls -Value $Url -Encoding UTF8
