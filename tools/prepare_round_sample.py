"""Reduce the CC BY 4.0 player-round file to public, dated sporting observations.
Build-time tool only. Install pyarrow==20.0.0 to regenerate from the published file.
"""

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import timezone
from pathlib import Path
import re

DIGEST = "5be61eb102d2edd8163709c5ccd1a6736c87dca7cadbbdca710350b1bd45a294"
OUT = Path(__file__).with_name("scene_sources") / "round-sample.json.gz"


def normalized(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_sides(groups, teams):
    """Map clan tags to the two series participants only when unambiguous."""
    resolved = {}
    for roster, group in groups.items():
        if len(group["labels"]) != 1:
            continue
        tag = normalized(next(iter(group["labels"])))
        if not tag:
            continue
        exact = [i for i, team in enumerate(teams) if normalized(team) == tag]
        if len(exact) == 1:
            resolved[roster] = exact[0]
            continue
        near = [
            i
            for i, team in enumerate(teams)
            if len(normalized(team)) >= 3
            and (
                tag == "team" + normalized(team)
                or tag == normalized(team) + "gaming"
                or tag == normalized(team) + "esports"
                or tag == normalized(team) + "esport"
            )
        ]
        if len(near) == 1:
            resolved[roster] = near[0]
    if len(groups) == 2 and len(resolved) == 1:
        other = next(k for k in groups if k not in resolved)
        resolved[other] = 1 - next(iter(resolved.values()))
    return resolved if len(set(resolved.values())) == len(resolved) else {}


def prepare(path):
    import pyarrow.parquet as pq

    with path.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != DIGEST:
            raise ValueError(
                "Ожидается проверенный файл sneakyzero (ноябрьская публикация)"
            )
    parquet = pq.ParquetFile(path)
    maps, players = {}, defaultdict(Counter)
    columns = "map_uid match_id map_index event team1 team2 series_score1 series_score2 map_name match_date steamid player_name team_name_resolved roster_uid inventory_json player_active_at_freeze_end".split()
    for batch in parquet.iter_batches(batch_size=8192, columns=columns):
        for (
            mid,
            series,
            ix,
            event,
            a,
            b,
            s1,
            s2,
            map_name,
            dt,
            pid,
            nick,
            tag,
            roster,
            inventory,
            active,
        ) in zip(*(col.to_pylist() for col in batch.columns)):
            if not active or not pid or not nick or not roster:
                continue
            if mid not in maps:
                maps[mid] = dict(
                    series=series,
                    index=ix,
                    event=event,
                    teams=[a, b],
                    score=[s1, s2],
                    map=map_name.removeprefix("de_"),
                    day=dt.astimezone(timezone.utc).date().isoformat(),
                    groups={},
                )
            group = maps[mid]["groups"].setdefault(
                roster, dict(labels=set(), players={})
            )
            if tag:
                group["labels"].add(tag)
            players[pid][nick] += 1
            usage = group["players"].setdefault(pid, [0, 0, 0])
            equipment = set(json.loads(inventory or "[]"))
            usage[0] += 1
            usage[1] += int("AWP" in equipment)
            usage[2] += int(
                bool(
                    equipment
                    & {
                        "Flashbang",
                        "Smoke Grenade",
                        "Smoke Grenade (CT)",
                        "Smoke Grenade (T)",
                    }
                )
            )
    for m in maps.values():
        groups = m.pop("groups")
        lookup = resolve_sides(groups, m["teams"])
        m["sides"] = [None, None]
        for key, i in lookup.items():
            members = groups[key]["players"]
            if len(members) == 5:
                m["sides"][i] = members
    return dict(
        players={
            k: [n for n, count in counts.most_common()]
            for k, counts in sorted(players.items())
        },
        maps=sorted(maps.values(), key=lambda m: (m["day"], m["series"], m["index"])),
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("parquet", type=Path)
    args = cli.parse_args()
    result = prepare(args.parquet)
    OUT.write_bytes(
        gzip.compress(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode(),
            mtime=0,
        )
    )
    print(len(result["players"]), len(result["maps"]), OUT)
