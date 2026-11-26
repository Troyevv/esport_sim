"""Build roster-linked sporting facts from a local, pinned Valve checkout and the scene."""

import argparse
import gzip
import json
import subprocess
from pathlib import Path

from backend import database
from backend.valve_import import COMMIT, ident
from tools.november_scene import DIR, team_key


def load_lists(repo, stamp):
    by_roster = {}
    for region in ("global", "europe", "americas", "asia"):
        path = f"invitation/2026/standings_{region}_{stamp}.md"
        body = subprocess.check_output(
            ["git", "-C", repo, "show", f"{COMMIT}:{path}"]
        ).decode()
        for line in body.splitlines():
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            if not cells or not cells[0].isdigit():
                continue
            rank, points, name, five = cells[:4]
            key = tuple(sorted(n.strip().casefold() for n in five.split(",")))
            if region == "global":
                by_roster[key] = dict(
                    rank=int(rank),
                    points=int(points),
                    name=name,
                    nicks=five.split(", "),
                )
            else:
                by_roster[key].update(region=region.title(), regional=int(rank))
    return by_roster.values()


def build(repo):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    current = {r["team"]: r["players"] for r in pack["rosters"].values()}
    names = {pid: p["name"].casefold() for pid, p in pack["players"].items()}
    teams = {t: {names[p]: p for p in five} for t, five in current.items()}
    snapshots = {}
    for stamp in ("2026_08_03", "2026_09_07", "2026_10_05", "2026_11_02"):
        rows = []
        for row in load_lists(repo, stamp):
            roster = {n.casefold() for n in row["nicks"]}
            matched = [
                t for t, players in teams.items() if len(roster & players.keys()) >= 3
            ]
            # A nickname collision cannot establish continuity across clubs.
            if len(matched) == 1:
                tid = matched[0]
                row.update(
                    team=tid,
                    core=[teams[tid][n] for n in sorted(roster & teams[tid].keys())],
                )
            rows.append(row)
        snapshots[stamp.replace("_", "-")] = rows
    major = []
    for squad in json.loads((DIR / "singapore-202611.json").read_bytes()):
        tid = ident("t", team_key(squad["name"]))
        five = [nick.casefold() for nick, _, _ in squad["players"]]
        name_to_ids = {}
        for pid, nick in names.items():
            name_to_ids.setdefault(nick, []).append(pid)

        def resolve(nick):
            existing = teams[tid].get(nick)
            ids = name_to_ids.get(nick, [])
            return existing or (ids[0] if len(ids) == 1 else None)

        players = [
            resolve(nick)
            or next(
                (
                    pid
                    for pid, p in pack["players"].items()
                    if p["realName"] == name and name
                ),
                None,
            )
            for nick, (_, name, _) in zip(five, squad["players"], strict=True)
        ]
        assert all(players) and len(set(players)) == 5, (
            squad["name"],
            five,
            players,
            teams[tid],
        )
        sub = resolve(squad["sub"][0].casefold()) if squad["sub"] else None
        coach = next(k for k, v in pack["staff"].items() if v["team"] == tid)
        major.append(
            dict(
                team=tid,
                alias=squad["name"],
                players=players,
                reserves=[sub] if sub else [],
                coach=coach,
            )
        )
    payload = dict(version=1, model=COMMIT, snapshots=snapshots, major=major)
    output = database.STARTER.with_name("competitions") / "november-2026.json.gz"
    output.write_bytes(
        gzip.compress(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            mtime=0,
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("repository", type=Path)
    build(cli.parse_args().repository)
