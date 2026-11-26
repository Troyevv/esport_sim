"""Record actual team loadouts and cash flows after a shared BO1 freeze time."""

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
import random
from unittest.mock import patch

from backend import career, cs2_economy, cs2_maps, database, match_inventory
from tools.cs2_tactical_audit import run


def record(pack, name, output):
    rosters = sorted(career.roster_index(pack).values())
    buy = cs2_economy.buy
    rows = []

    def observe(world, squad, strategy, purchase, board):
        before = sum(p["cash"] for p in squad)
        paid = Counter()
        cost = 0

        def debit(state, actor, item, recipient=None):
            nonlocal cost
            wallet = actor["cash"]
            result = purchase(state, actor, item, recipient)
            if result:
                cost += wallet - actor["cash"]
                paid[item] += 1
            return result

        buy(world, squad, strategy, debit, board)
        after = sum(p["cash"] for p in squad)
        assert before - after == cost
        rows.append(dict(
            seed=seed, mirror=mirror, round=world["round"], side=squad[0]["team"],
            budget=strategy["budget"], context=strategy["context"],
            scenario=strategy["scenario"], before=before, after=after,
            spent=cost, bought=dict(paid), armor=sum(p["armor"] > 0 for p in squad),
            helmets=sum(p["helmet"] for p in squad), kits=sum(p["kit"] for p in squad),
            primaries=sum(bool(match_inventory.slots(p)[0]) for p in squad),
            utility=sum(len(p["utility"]) for p in squad),
        ))

    with patch.object(cs2_economy, "buy", observe):
        for seed in (41000, 59000):
            pair = random.Random(seed).sample(rosters, 2)
            for mirror, teams in enumerate((pair, pair[::-1])):
                run(name, seed, teams, pack, False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    package = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    record(package, args.map, args.out)
