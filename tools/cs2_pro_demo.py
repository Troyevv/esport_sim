"""Measure thrown utility and surviving CTs from a fixed sample of professional demos."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve

import pyarrow.parquet as pq
from demoparser2 import DemoParser


def parse(path, rounds):
    parser = DemoParser(str(path))
    # Source 2 reports a detonation per projectile. Inferno damage ticks would
    # count the same incendiary repeatedly; use only its initial ignition.
    event_types = {
        "flashbang_detonate": "flashbang",
        "hegrenade_detonate": "hegrenade",
        "smokegrenade_detonate": "smokegrenade",
        "inferno_startburn": "fire",
        "decoy_started": "decoy",
    }
    throws = []
    for event, kind in event_types.items():
        records = parser.parse_event(event)
        if len(records):
            throws.extend((int(tick), kind) for tick in records["tick"])
    if not throws:
        raise ValueError("No utility detonations in professional demo")

    def ticks(event):
        rows = parser.parse_event(event)
        return list(map(int, rows["tick"])) if len(rows) else []

    taps = ticks("bomb_begindefuse")
    plants = ticks("bomb_planted")
    # Some GOTV servers omit the begin-use game event. Sample the recorded
    # pawn flag at quarter-second intervals after the plant as a second witness.
    checks = set()
    for row in rounds:
        plant = next(
            (t for t in plants if row["freeze_end_tick"] <= t <= row["end_tick"]), None
        )
        if plant is not None:
            checks.update(range(plant, row["end_tick"], 16))
    if checks:
        flags = parser.parse_ticks(["is_defusing", "team_num"], ticks=sorted(checks))
        taps.extend(
            int(t)
            for t in flags.loc[
                (flags.team_num == 3) & (flags.is_defusing == True), "tick"
            ].unique()
        )
    ends = [r["end_tick"] for r in rounds]
    players = parser.parse_ticks(["health", "team_num"], ticks=ends)
    # A round has one snapshot per phase, taken from the recorded server tick.
    sample = {}
    for r in rounds:
        start, end = r["freeze_end_tick"], r["end_tick"]
        sample[r["round_num"]] = {
            sec: start + 64 * sec
            for sec in (0, 10, 25, 45, 70)
            if start + 64 * sec < end
        }
    ticks = sorted({t for group in sample.values() for t in group.values()})
    radar = parser.parse_ticks(
        ["X", "Y", "Z", "health", "team_num", "current_equip_value"], ticks=ticks
    )
    grouped = dict(tuple(radar.groupby("tick")))
    freeze = parser.parse_ticks(
        ["health", "team_num", "balance", "cash_spent_this_round", "inventory"],
        ticks=sorted({r["freeze_end_tick"] for r in rounds}),
    )
    wallets = {}
    active = freeze[(freeze.health > 0) & freeze.team_num.isin([2, 3])]
    for tick, group in active.groupby("tick"):
        if len(group) != 10 or group.steamid.nunique() != 10:
            continue
        wallets[int(tick)] = {
            str(p.steamid): dict(
                side="T" if p.team_num == 2 else "CT",
                remaining=int(p.balance),
                spent=int(p.cash_spent_this_round),
                loadout=list(p.inventory) if p.inventory is not None else [],
            )
            for p in group.itertuples()
        }
    result = []
    for row in rounds:
        start, end = row["freeze_end_tick"], row["end_tick"]
        counter = Counter(kind for tick, kind in throws if start <= tick <= end)
        alive = players[
            (players.tick == end) & (players.health > 0) & (players.team_num == 3)
        ]
        positions = {}
        for sec, tick in sample[row["round_num"]].items():
            frame = grouped.get(tick)
            if frame is not None:
                live = frame[(frame.health > 0) & (frame.team_num.isin([2, 3]))]
                positions[sec] = [
                    [
                        int(p.team_num),
                        str(p.steamid),
                        round(p.X),
                        round(p.Y),
                        round(p.Z),
                        int(p.current_equip_value or 0),
                    ]
                    for p in live.itertuples()
                ]
        result.append(
            dict(
                radar=positions,
                wallets=wallets.get(start),
                round=row["round_num"],
                winner=row["winner_side"],
                reason=row["end_reason"],
                plant=row["bomb_planted"],
                plantSeconds=next(
                    ((t - start) / 64 for t in plants if start <= t <= end), None
                ),
                touched=any(start <= t <= end for t in taps),
                duration=(end - start) / 64,
                grenades=dict(counter),
                survivingCT=len(alive),
            )
        )
    if any(r["reason"] == "bomb_defused" and not r["touched"] for r in result):
        for r in result:
            r["touched"] = None
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", required=True)
    p.add_argument("--dir", type=Path, required=True)
    args = p.parse_args()
    maps = pq.read_table(args.dir / "full_maps.parquet").to_pylist()
    matches = [
        m for m in maps if m["map_name"] == args.map and m["analysis_eligible_v1"]
    ]
    matches.sort(key=lambda m: (-m["hltv_stars"], m["map_uid"]))
    all_rounds = pq.read_table(args.dir / "full_rounds.parquet").to_pylist()
    output = []
    for m in matches[:2]:
        url = f"https://huggingface.co/datasets/{m['source_repo']}/resolve/{m['source_revision']}/{m['source_file_name']}"
        rounds = [r for r in all_rounds if r["map_uid"] == m["map_uid"]]
        with TemporaryDirectory() as directory:
            demo = Path(directory) / "match.dem"
            urlretrieve(url, demo)
            with demo.open("rb") as reader:
                assert (
                    file_digest(reader, "sha256").hexdigest() == m["source_demo_sha256"]
                )
            rows = parse(demo, rounds)
        output.append(
            dict(
                map=m["map_name"],
                date=str(m["match_date"]),
                stars=m["hltv_stars"],
                match=m["match_id"],
                event=m["event"],
                patch=m["patch_version"],
                rounds=rows,
            )
        )
    (args.dir / (args.map + "-utility.json")).write_text(json.dumps(output))


if __name__ == "__main__":
    main()
