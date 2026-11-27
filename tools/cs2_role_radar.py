"""Record matched first-person movement and role decisions in full production BO1s."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import random

from tests.reference_kernel import cs2_maps, match
from backend import career, database, world
from tools.cs2_skill_audit import lineups


PROFILES = {
    "entry_aggressive": ("entry", {"aggression": 90, "risk": 90, "patience": 35}),
    "entry_cautious": ("entry", {"aggression": 35, "risk": 35, "patience": 90}),
    "caller": ("igl", {"calling": 90, "leadership": 90, "game_reading": 90, "communication": 90}),
    "scope": ("awper", {"sniper_rifles": 90, "positioning": 90, "patience": 90}),
    "support": ("support", {"support": 90, "discipline": 90, "flashes": 90, "coordination": 90}),
}


def record(pack, name, seed, pair, mirror, variant):
    teams = pair[::-1] if mirror else pair
    domain = lineups(pack, pair, teams, name, "balanced")
    members = world.lineup(domain, pair[0])
    assigned = {role: next(m["player"] for m in members if m["role"] == role)
                for role in ("entry", "awper", "support")}
    assigned["igl"] = next(m["player"] for m in members if m["captain"])
    if variant in PROFILES:
        role, changes = PROFILES[variant]
        domain["players"][assigned[role]]["skills"].update(changes)
    game = match.initial(seed, domain, teams, map_id=name)
    totals = {role: Counter() for role in assigned}
    radar = {}
    while game["phase"] != "finished":
        match.advance(game)
        if game["phase"] not in ("live", "planted") or game["tick"] % 10:
            continue
        for a in game["agents"]:
            if a["club"] != int(mirror) or not a["hp"]:
                continue
            for role, pid in assigned.items():
                if a["playerId"] == pid:
                    totals[role][a["status"]] += 1
                    if game["round"] == 1:
                        radar.setdefault(role, []).append([*cs2_maps.xyz(a), a["heading"], a["status"]])
    return dict(map=name, seed=seed, teams=teams, mirror=mirror, profile=variant, rounds=len(game["history"]),
                statuses=totals, captainRole=next(m["role"] for m in members if m["captain"]), radar=radar)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(rid for rid in career.roster_index(pack).values()
                     if {"awper", "entry", "support"} <= {pack["players"][pid]["role"] or world.SLOT_ROLES[i]
                     for i, pid in enumerate(pack["rosters"][rid]["players"])})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as stream:
        for seed in (41000,59000):
            pair = random.Random(seed).sample(rosters, 2)
            for mirror in (False,True):
                for variant in ("balanced", *PROFILES):
                    row = record(pack, args.map, seed, pair, mirror, variant)
                    print(json.dumps(row, ensure_ascii=False), file=stream, flush=True)


if __name__ == "__main__":
    main()
