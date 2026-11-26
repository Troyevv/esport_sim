"""Condense the public 2026-11-25 Liquipedia matchdata artifact at the career boundary."""

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from zipfile import ZipFile

from backend import database
from backend.competition_catalog import DATA
from tools.november_scene import team_key

CUTOFF = int(datetime(2026, 11, 25, tzinfo=UTC).timestamp())
SHA = "e36192611f91c4a1847080c0ed5324aed4b90134afb85ca1b4d413d1928c5ccb"


def build(archive):
    with open(archive, "rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != SHA:
            raise ValueError("Неизвестная редакция истории")
    with ZipFile(archive) as z:
        raw = json.loads(z.read("matchdata.json"))
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    club_names = {team_key(t["name"]): tid for tid, t in pack["teams"].items()}
    nicknames = defaultdict(set)
    for p, player in pack["players"].items():
        nicknames[player["name"].casefold()].add(p)
    valid = [
        m
        for m in raw["matches"]
        if m["valveRanked"] and all(len(m[f"team{n}Players"]) == 5 for n in (1, 2))
    ]
    last = {}
    for m in valid:
        eid = m["eventId"]
        last[eid] = max(last.get(eid, 0), m["matchStartTime"])
    events = {}
    for e in raw["events"]:
        eid = e["eventId"]
        end = e.get("endDate")
        if (
            not e["finished"]
            or last.get(eid, CUTOFF) >= CUTOFF
            or end
            and end >= "2026-11-25"
            or "showmatch" in e["eventName"].lower()
        ):
            continue
        payout = {}
        linked = None
        for row in e["prizeDistribution"]:
            payout[row["teamId"]] = row["prize"] + row["clubShare"]
            if row["qualifiedEvents"]:
                linked = ",".join(map(str, row["qualifiedEvents"]))
        pool = e["prizePool"].replace(",", "").removeprefix("$")
        events[eid] = dict(
            name=e["eventName"],
            placements={
                str(r["teamId"]): r["placement"] for r in e["prizeDistribution"]
            },
            end=end or datetime.fromtimestamp(last[eid], UTC).date().isoformat(),
            lastMatch=last[eid],
            lan=e["lan"],
            pool=min(int(pool), 1000000) if pool.isdigit() else 0,
            payouts=payout,
            linked=linked,
        )
    valid = [
        m
        for m in valid
        if m["eventId"] in events
        and CUTOFF - 180 * 86400 <= m["matchStartTime"] < CUTOFF
    ]
    identities = defaultdict(set)
    nick_by_id = {}
    for m in valid:
        for n in (1, 2):
            for p in m[f"team{n}Players"]:
                identities[p["nick"].casefold()].add(p["playerId"])
                nick_by_id[p["playerId"]] = p["nick"]

    def person(pid):
        name = nick_by_id[pid].casefold()
        return (
            next(iter(nicknames[name]))
            if len(identities[name]) == len(nicknames[name]) == 1
            else "lp:" + str(pid)
        )

    clubs = {}
    players = {}
    matches = []
    for m in valid:
        orgs = []
        fives = []
        for n in (1, 2):
            org = m[f"team{n}Id"]
            name = m[f"team{n}Name"]
            clubs[org] = dict(name=name, team=club_names.get(team_key(name)))
            orgs.append(org)
            five = []
            for p in m[f"team{n}Players"]:
                pid = person(p["playerId"])
                players[pid] = dict(nick=p["nick"], country=p["countryIso"].upper())
                five.append(pid)
            fives.append(five)
        matches.append(
            dict(
                date=m["matchStartTime"],
                event=m["eventId"],
                teams=orgs,
                winner=orgs[m["winningTeam"] - 1],
                winnerIndex=m["winningTeam"] - 1,
                fives=fives,
                nicks=[[p["nick"] for p in m[f"team{n}Players"]] for n in (1, 2)],
                ranked=True,
                forfeit=m["forfeited"],
            )
        )
    payload = dict(
        version=1,
        cutoff=CUTOFF,
        clubs=clubs,
        players=players,
        matches=matches,
        events=events,
    )
    output = DATA / "vrs-history-20261125.json.gz"
    output.write_bytes(
        gzip.compress(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            mtime=0,
        )
    )
    print(len(matches), len(events), len(players), output.stat().st_size)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive")
    build(cli.parse_args().archive)
