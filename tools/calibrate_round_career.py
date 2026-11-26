"""Manual distribution check on actual November rosters and optional detailed reports."""

import argparse
import json
from collections import Counter
from pathlib import Path
from random import Random
from statistics import mean
from tempfile import TemporaryDirectory

from backend import career, database, round_sim, veto, world
from backend.store import Store


def metrics(maps):
    scores = [max(m["score"]) - min(m["score"]) for m in maps]
    rows = [r for m in maps for r in m["rounds"]]
    stats = [p for m in maps for p in m["stats"]]
    seats = 10 * len(rows)
    return dict(
        maps=len(maps),
        rounds=len(rows),
        roundsPerMap=len(rows) / len(maps),
        ot=sum(len(m["rounds"]) > 24 for m in maps) / len(maps),
        margins=dict(
            Counter("1–3" if v <= 3 else "4–7" if v <= 7 else "8+" for v in scores)
        ),
        tWins=sum(r["side"] == "T" for r in rows) / len(rows),
        killsPerRound=sum(p["k"] for p in stats) / seats,
        adr=sum(p["damage"] for p in stats) / seats,
        kast=sum(p["kast"] for p in stats) / seats,
    )


def measure(size, reference):
    with TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "calibration.sqlite")
        pack = store.careers.pack([database.STAFF_RELEASE, 1])
        ids = career.roster_index(pack)
        rng = Random(20261125)
        maps, groups = [], {}
        for seed in range(size):
            teams = rng.sample(sorted(ids), 2)
            rids = [ids[t] for t in teams]
            if set(pack["rosters"][rids[0]]["players"]) & set(
                pack["rosters"][rids[1]]["players"]
            ):
                continue
            domain = database.match_input(pack, rids)
            map_id = veto.ACTIVE[seed % len(veto.ACTIVE)]
            strengths = [world.team_rating(domain, r, map_id[3:]) for r in rids]
            m = round_sim.play_map(
                dict(domain=domain, rosterIds=rids), map_id, teams[seed % 2], seed
            )
            maps.append(m)
            delta = strengths[0] - strengths[1]
            if delta:
                bucket = (
                    "1–4" if abs(delta) < 5 else "5–9" if abs(delta) < 10 else "10+"
                )
                groups.setdefault(bucket, []).append(
                    teams[int(delta < 0)] != m["winnerTeamId"]
                )
        pro = [p["statistics"] for p in pack["players"].values() if p.get("statistics")]
        print(
            json.dumps(
                dict(
                    roundModel=metrics(maps),
                    underdogs={k: [len(v), mean(v)] for k, v in groups.items()},
                    proFinalPlayers=len(pro),
                    proFinalMeanADR=mean(p["adr"] for p in pro),
                ),
                indent=2,
            )
        )
        if reference:
            reports = json.loads(reference.read_text())["samples"]
            print(
                json.dumps(
                    metrics([m for r in reports for m in r.get("maps", [r])]), indent=2
                )
            )
        store.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", type=int, default=1200)
    parser.add_argument("--detailed", type=Path)
    args = parser.parse_args()
    measure(args.maps, args.detailed)
