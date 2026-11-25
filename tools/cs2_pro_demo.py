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
    event_types = {"flashbang_detonate":"flashbang", "hegrenade_detonate":"hegrenade",
                   "smokegrenade_detonate":"smokegrenade", "inferno_startburn":"fire",
                   "decoy_started":"decoy"}
    throws = []
    for event, kind in event_types.items():
        records = parser.parse_event(event)
        if len(records):
            throws.extend((int(tick), kind) for tick in records["tick"])
    if not throws:
        raise ValueError("No utility detonations in professional demo")
    ends = [r["end_tick"] for r in rounds]
    players = parser.parse_ticks(["health","team_num"], ticks=ends)
    result = []
    for row in rounds:
        start,end=row["freeze_end_tick"],row["end_tick"]
        counter=Counter(kind for tick, kind in throws if start <= tick <= end)
        alive = players[(players.tick == end) & (players.health > 0) & (players.team_num == 3)]
        result.append(dict(round=row["round_num"],winner=row["winner_side"],reason=row["end_reason"],
                           plant=row["bomb_planted"],duration=(end-start)/64,
                           grenades=dict(counter),survivingCT=len(alive)))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map",required=True)
    p.add_argument("--dir",type=Path,required=True)
    args=p.parse_args()
    maps=pq.read_table(args.dir/"full_maps.parquet").to_pylist()
    matches=[m for m in maps if m["map_name"] == args.map and m["analysis_eligible_v1"]]
    matches.sort(key=lambda m:(-m["hltv_stars"],m["map_uid"]))
    all_rounds=pq.read_table(args.dir/"full_rounds.parquet").to_pylist()
    output=[]
    for m in matches[:2]:
        url=f"https://huggingface.co/datasets/{m['source_repo']}/resolve/{m['source_revision']}/{m['source_file_name']}"
        rounds=[r for r in all_rounds if r["map_uid"]==m["map_uid"]]
        with TemporaryDirectory() as directory:
            demo=Path(directory)/"match.dem"
            urlretrieve(url,demo)
            with demo.open("rb") as reader:
                assert file_digest(reader,"sha256").hexdigest()==m["source_demo_sha256"]
            rows=parse(demo,rounds)
        output.append(dict(map=m["map_name"],date=str(m["match_date"]),stars=m["hltv_stars"],
                           match=m["match_id"],event=m["event"],patch=m["patch_version"],rounds=rows))
    (args.dir/(args.map+"-utility.json")).write_text(json.dumps(output))


if __name__=="__main__":
    main()
