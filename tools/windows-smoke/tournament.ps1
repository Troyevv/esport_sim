function Test-AuroraTournament([string]$Origin) {
    function Apply-Action([string]$Kind, $Value = $null) {
        $s = Invoke-RestMethod "$Origin/api/state"
        $body = @{id=[guid]::NewGuid().ToString(); context=$s.context; revision=$s.revision; kind=$Kind}
        if ($null -ne $Value) { $body.value = $Value }
        $null = Invoke-RestMethod "$Origin/api/command" -Method Post -Headers @{Origin=$Origin} -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 8 -Compress)
    }
    $options = Invoke-RestMethod "$Origin/api/career/options/scene-20261125-staff/1"
    $team = ($options.teams | Where-Object { $_.name -eq 'Aurora Gaming' }).id
    Apply-Action 'career-create' @{id='scene-20261125-staff';revision=1;team=$team;name='Aurora';mode='owner';scope='full'}
    $c = (Invoke-RestMethod "$Origin/api/career").active
    $league = 'ecl-eu-2026-13'
    $major = 'pgl-major-2026'
    $catalog = Invoke-RestMethod "$Origin/api/career/$($c.id)/competitions"
    $clash = ($catalog.editions | Where-Object id -eq $league).conflicts
    if ($clash.id -notcontains $major -or $clash.dates -notcontains '2026-12-03') { throw 'Expected Aurora Major/ECL overlap.' }
    Apply-Action 'career-entry' @{action='prioritise';edition=$league;release=@($major)}
    Apply-Action 'career-entry' @{action='submit';edition=$league;players=@($c.roster.id);reserves=@();coach=$null}
    Apply-Action 'career-save' @{slot='1'}
    Apply-Action 'career-load' @{slot='1'}
    $c = (Invoke-RestMethod "$Origin/api/career").active
    if (@($c.attention | Where-Object level -eq 'required').Count) { throw 'Unexpected mandatory decision after registration.' }
    $fixture = $c.queue[0]
    if (!$fixture.edition -or $fixture.date -ne $c.date) { throw 'Expected real tournament fixture on the starting day.' }
    Apply-Action 'career-watch' @{fixture=$fixture.id}
    Apply-Action 'career-play'
    Apply-Action 'series-next'
    $world = (Invoke-RestMethod "$Origin/api/state").world
    if (!$world.match -or !$world.series -or $world.map.id -notmatch '^de_' -or $world.map.id -ne $world.series.order[0].map) { throw 'Tournament did not start on its selected CS2 map.' }
    Write-Output "Aurora: conflict resolved, lineup restored and tournament $($fixture.edition) launched on $($world.map.id)."
}
