# Execute in a fresh Windows process after importing the disposable test root,
# independent of the earlier Schannel / ServicePoint negative control.
param([Parameter(Mandatory)][string]$Lan, [Parameter(Mandatory)][string]$Origin)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
$handler = [Net.Http.HttpClientHandler]::new()
$handler.UseProxy = $false
$client = [Net.Http.HttpClient]::new($handler)
$client.DefaultRequestHeaders.Add('Origin', $Lan)
try {
    $access = $client.GetAsync("$Lan/api/state").GetAwaiter().GetResult()
    if ([int]$access.StatusCode -ne 401) { throw "Unexpected unpaired response: $($access.StatusCode)" }
    $invite = Invoke-RestMethod "$Origin/api/host/invite" -Method Post -Headers @{Origin=$Origin}
    if ([string]::IsNullOrEmpty($invite.code)) { throw 'Invitation unavailable' }
    $json = @{code=$invite.code; name='Windows smoke test'} | ConvertTo-Json -Compress
    $content = [Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, 'application/json')
    $paired = $client.PostAsync("$Lan/api/pair", $content).GetAwaiter().GetResult()
    if ([int]$paired.StatusCode -ne 200) { throw "Pair failed: $($paired.StatusCode)" }
    $state = $client.GetStringAsync("$Lan/api/state").GetAwaiter().GetResult() | ConvertFrom-Json
    if ($state.context -ne (Invoke-RestMethod "$Origin/api/state").context) { throw 'Paired device has different world.' }
} catch {
    $reason = $_.Exception
    while ($null -ne $reason) {
        Write-Warning ("TLS: {0}: {1}" -f $reason.GetType().Name, $reason.Message)
        $reason = $reason.InnerException
    }
    # Inspect only the leaf public certificate. Never log the PEM private key.
    $combined = [IO.File]::ReadAllText((Join-Path $env:LOCALAPPDATA 'EsportSim\lan-identity\server.pem'))
    $public = [regex]::Match($combined, '(?s)-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----')
    if ($public.Success) {
        $der = [Convert]::FromBase64String($public.Groups[1].Value)
        $leaf = [Security.Cryptography.X509Certificates.X509Certificate2]::new($der)
        $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
        try {
            $valid = $chain.Build($leaf)
            Write-Warning "Windows X509Chain.Build=$valid; endpoint=$Lan, public leaf=$($leaf.Subject)"
            foreach ($item in $chain.ChainElements) {
                Write-Warning ("Element {0}; {1}" -f $item.Certificate.Subject, ($item.ChainElementStatus.Status -join ','))
            }
            foreach ($status in $chain.ChainStatus) {
                Write-Warning ("X509Chain status: {0}; {1}" -f $status.Status,$status.StatusInformation.Trim())
            }
            $path = Join-Path $env:TEMP 'esport-smoke-public-leaf.cer'
            [IO.File]::WriteAllBytes($path, $der)
            $ip = ([uri]$Lan).Host
            & certutil -verify -sslpolicy $ip $path | ForEach-Object { Write-Warning $_ }
        } finally {
            $chain.Dispose()
            $leaf.Dispose()
        }
    }
    throw
} finally { $client.Dispose() }
