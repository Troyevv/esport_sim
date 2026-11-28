"""Manual R5.5.6 acceptance on one installed map. Run outside CI."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import random
from time import process_time

import psutil

from backend import career, checkpoints, cs2_maps, database, match, match_score, native_match_state
from backend.match_rules import RULES


def audit_round(number, events, result):
    kinds = Counter(e['kind'] for e in events)
    assert kinds['round_start'] == kinds['round_end'] == 1
    assert number == result['round']
    assert checkpoints.purchases(events) == result['economy']
    end = next(e for e in events if e['kind'] == 'round_end')
    assert all(end[k] == result[k] for k in ('winner', 'winnerTeamId', 'side', 'reason'))
    assert kinds['defuse'] == (result['reason'] == 'Обезвреживание')
    assert kinds['explode'] == (result['reason'] == 'Взрыв C4')
    assert kinds['defuse'] + kinds['explode'] <= kinds['plant'] <= 1
    if kinds['defuse'] or kinds['explode']:
        plant = next(e for e in events if e['kind'] == 'plant')
        finish = next(e for e in events if e['kind'] in ('defuse', 'explode'))
        assert plant['id'] < finish['id'] < end['id']
        assert end['side'] == ('T' if finish['kind'] == 'explode' else 'CT')
    duration = end['tick'] - events[0]['tick']
    assert duration == result['duration'] <= RULES['freeze'] + RULES['live'] + RULES['fuse']
    return duration


def audit(game):
    checkpoints.validate_current(game)
    match_score.validate(game)
    clubs = {a['id']: a['club'] for a in game['agents']}
    stats = {actor: Counter() for actor in clubs}
    balances = Counter()
    counts = Counter()
    serial = last_tick = longest = 0
    journals = [*game['archive'], game['events']]
    for number, (events, result) in enumerate(zip(journals, game['history'], strict=True), 1):
        longest = max(longest, audit_round(number, events, result))
        alive = set(clubs)
        contributions = set()
        for e in events:
            serial += 1
            assert (e['id'], e['round']) == (serial, number) and last_tick <= e['tick']
            last_tick = e['tick']
            kind = e['kind']
            actor = e.get('player')
            counts[kind] += 1
            if kind == 'money':
                balances[actor] += e['amount']
                assert balances[actor] == e['balance'] and 0 <= e['balance'] <= RULES['cap']
            elif kind == 'buy':
                stats[actor]['spent'] += e['price']
            elif kind == 'damage' and clubs[actor] != clubs[e['target']]:
                stats[actor]['damage'] += e['amount']
            elif kind == 'kill':
                alive.remove(e['target'])
                stats[e['target']]['d'] += 1
                assert e['enemy'] == (clubs[actor] != clubs[e['target']])
                if e['enemy']:
                    contributions.add(actor)
                    stats[actor]['k'] += 1
                    stats[actor]['hs'] += e['head']
                    stats[actor]['opening'] += e['opening']
                if e['trade']:
                    contributions.add(e['trade'])
                for helper in e['assists']:
                    contributions.add(helper)
                    stats[helper]['a'] += 1
            elif kind == 'defense_call':
                counts[e['decision'] + 'Calls'] += 1
            elif kind == 'throw':
                assert e['tick'] == e['start'] <= e['land'] <= e['end'] and len(e['trajectory']) >= 2
                counts['throws' + e['team']] += 1
        for actor in contributions | alive:
            stats[actor]['kast'] += 1
    assert game['phase'] == 'finished' and counts['match_end'] == 1
    final_event = game['events'][-1]
    assert final_event['kind'] == 'match_end' and final_event['winnerTeamId'] == game['winnerTeamId']
    assert serial == game['serial'] and last_tick == game['tick']
    for a in game['agents']:
        actor = a['id']
        assert balances[actor] == a['cash']
        for key in ('k', 'd', 'a', 'hs', 'opening', 'damage', 'spent', 'kast'):
            assert stats[actor][key] == game['stats'][actor][key], (game['mapId'], game['seed'], actor, key)
    return dict(maxRoundTicks=longest, events=serial, **{key: counts[key] for key in
                ('buy', 'kill', 'plant', 'defuse', 'explode', 'interrupt', 'throwsT', 'throwsCT', 'retakeCalls', 'saveCalls')})


def play(world, resume=False):
    owner = native_match_state.open_game(world)
    batch = 127 if resume else 512
    tick = 0
    proc = psutil.Process()
    peak = proc.memory_info().rss
    cpu = process_time()
    if resume:
        tick = owner.advance(180)
        saved = json.loads(owner.snapshot())
        assert tick == 180 and saved['phase'] in ('live', 'planted')
        owner = native_match_state.open_game(saved)
    while True:
        advanced = owner.advance(batch)
        tick += advanced
        peak = max(peak, proc.memory_info().rss)
        if advanced < batch:
            break
        if tick > 150_000:
            raise RuntimeError(f"Match exceeded audit tick budget at {tick}")
    elapsed = process_time() - cpu
    raw = owner.snapshot()
    game = json.loads(raw)
    assert game['phase'] == 'finished' and game['tick'] == tick
    return game, hashlib.sha256(raw).hexdigest(), elapsed, peak


def run(name, output):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))['package']
    rosters = sorted(career.roster_index(pack).values())
    rows = []
    for base in (55300, 55600):
        seed = base + list(cs2_maps.NAMES).index(name)
        pair = random.Random(seed).sample(rosters, 2)
        domain = database.match_input(pack, pair)
        for start, roster in enumerate(pair):
            world = match.initial(seed, domain, pair, map_id=name, first_attack=domain['rosters'][roster]['team'])
            assert match_score.side_team(world, 'T') == domain['rosters'][roster]['team']
            game, digest, cpu, peak = play(world)
            results = audit(game)
            repeated = (name, seed) in {('de_nuke', 55606), ('de_anubis', 55301)}
            if repeated:
                again = play(world, resume=True)[1]
                assert again == digest, (name, seed, start, 'checkpoint replay')
            rows.append(dict(map=name, seed=seed, start=start, roster0=pair[0], roster1=pair[1],
                             score='-'.join(map(str, game['score'])), rounds=len(game['history']), ticks=game['tick'],
                             **results, cpuSeconds=round(cpu, 3), sampledRssMiB=round(peak / 2**20, 1),
                             resumedReplay=int(repeated), sha256=digest))
    with output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('map', choices=cs2_maps.NAMES)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.map, args.output)
