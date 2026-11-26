"""Offline standings calculation against Valve's November 2026 model.

Inputs are classified series. A match carries both actual fives; a completed event
supplies the prize per participant, LAN status and final date. No club OVR enters here.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from functools import lru_cache
import gzip
import json
from .competition_catalog import DATA
from math import log, log10, pi, sqrt

from .database import day

MODEL = "f8c55f250fdef796d708aa32814587932154fa04"


@lru_cache(maxsize=1)
def history():
    return json.loads(
        gzip.decompress((DATA / "vrs-history-20261125.json.gz").read_bytes())
    )


@lru_cache(maxsize=1)
def country_regions():
    return json.loads((DATA / "vrs-regions.json").read_bytes())


def nationality(pack, pid):
    country = pack["players"][pid].get("nationality")
    return (
        country
        if country in country_regions()
        else history()["players"].get(pid, {}).get("country")
    )


def plurality(regions):
    totals = Counter(regions)
    priority = ["Asia", "Americas", "Europe"]
    low = min((priority.index(r) for r in totals if r in priority), default=0)
    totals[priority[low]] += totals.pop("Africa", 0)
    return max(reversed(priority), key=lambda r: totals[r])


def timestamp(value):
    if isinstance(value, int):
        return value
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp())


def calculate(matches, events, cutoff, countries, regions, names=None):
    names = names or {}
    end = timestamp(cutoff)

    def age(value):
        return min(1, max(0, (180 * 86400 - (end - timestamp(value))) / (150 * 86400)))

    recent = sorted(
        (
            m
            for m in matches
            if end - 180 * 86400 <= timestamp(m["date"]) <= end
            and timestamp(events[m["event"]]["end"]) <= end
            and m["ranked"]
            and all(len(f) == 5 for f in m["fives"])
        ),
        key=lambda m: timestamp(m["date"]),
        reverse=True,
    )
    teams = []
    membership = defaultdict(set)
    games = []
    for m in recent:
        sides = []
        for side, (org, five) in enumerate(zip(m["teams"], m["fives"], strict=True)):
            players = set(five)
            overlap = Counter(idx for pid in players for idx in membership[pid])
            idx = min((idx for idx, n in overlap.items() if n >= 3), default=None)
            if idx is None:
                idx = len(teams)
                teams.append(
                    dict(
                        team=org,
                        base=set(),
                        lineups=[],
                        won=[],
                        prizes={},
                        pending=True,
                    )
                )
            t = teams[idx]
            if t["pending"]:
                for pid in t["base"]:
                    membership[pid].discard(idx)
                t.update(team=org, base=players, pending=m.get("forfeit", False))
                for pid in players:
                    membership[pid].add(idx)
            t["lineups"].append(
                list(
                    zip(
                        five,
                        m["nicks"][side]
                        if "nicks" in m
                        else [names.get(p, p) for p in five],
                        strict=True,
                    )
                )
            )
            t["prizes"].setdefault(
                m["event"], events[m["event"]]["payouts"].get(org, 0)
            )
            sides.append(idx)
        w = m["winnerIndex"] if "winnerIndex" in m else m["teams"].index(m["winner"])
        winner, loser = sides[w], sides[1 - w]
        teams[winner]["won"].append((loser, m))
        games.append((winner, loser, m["date"]))
    if not teams:
        return []

    def top(values):
        return sum(sorted(values, reverse=True)[:10])

    for t in teams:
        network = {}
        for opp, m in t["won"]:
            network.setdefault(opp, age(m["date"]))
        t["network"] = sum(network.values())
        t["lan"] = (
            top(age(m["date"]) for _, m in t["won"] if events[m["event"]]["lan"]) / 10
        )
        t["bounty"] = top(
            amount * age(events[e]["lastMatch"]) for e, amount in t["prizes"].items()
        )
    for factor in ("network", "lan", "bounty"):
        reference = sorted((t[factor] for t in teams), reverse=True)[
            min(4, len(teams) - 1)
        ]
        # The published JS produces NaN without a nonzero fifth reference.
        # Such sparse windows have no usable standings.
        if not reference:
            return []
        for t in teams:
            t[factor + "Ratio"] = min(1, t[factor] / reference)

    def curve(value):
        return 1 / (1 + abs(log10(value))) if value > 0 else 0

    # Valve resolves linked pools in event order. A previously visited target can
    # already include its own linked purse when another qualifier references it.
    pools = {eid: min(event["pool"], 1000000) for eid, event in events.items()}

    def js_order(key):
        key = str(key)
        return (
            (0, int(key))
            if key.isascii()
            and key.isdecimal()
            and str(int(key)) == key
            and int(key) < 2**32 - 1
            else (1, 0)
        )

    for eid in sorted(events, key=js_order):
        linked = events[eid].get("linked")
        chain = set()
        last = None
        while (
            linked in events
            and linked != eid
            and linked not in chain
            and timestamp(events[linked]["end"]) <= end
        ):
            chain.add(linked)
            last = linked
            linked = events[linked].get("linked")
        if last is not None:
            pools[eid] = min(1000000, pools[eid] + pools[last] * 0.5 ** len(chain))

    def stakes(eid):
        return curve(max(1, pools[eid]) / 1000000)

    for t in teams:
        opponents = [
            (teams[o], age(m["date"]) * stakes(m["event"])) for o, m in t["won"]
        ]
        t["seed"] = (
            curve(top(o["bountyRatio"] * weight for o, weight in opponents) / 10)
            + curve(t["bountyRatio"])
            + top(o["networkRatio"] * weight for o, weight in opponents) / 10
            + t["lanRatio"]
        ) / 4
    low = min(t["seed"] for t in teams)
    high = max(t["seed"] for t in teams)
    for t in teams:
        t["points"] = 400 + 1600 * (
            (t["seed"] - low) / (high - low) if high != low else 0.5
        )
    q = log(10) / 400
    g = 1 / sqrt(1 + 3 * (q * 75 / pi) ** 2)
    for winner, loser, date in sorted(games, key=lambda m: timestamp(m[2])):
        a, b = teams[winner], teams[loser]
        expected = 1 / (1 + 10 ** (-g * (a["points"] - b["points"]) / 400))
        info = age(date)
        variance = 1 / (1 / 75**2 + q * q * g * g * expected * (1 - expected) * info**2)
        delta = q * variance * g * (1 - expected) * info
        a["points"] += delta
        b["points"] -= delta
    rows = []
    regional = Counter()
    for t in sorted(teams, key=lambda t: -t["points"]):
        if len(t["lineups"]) < 5 or not t["network"]:
            continue
        last = t["lineups"][:10]
        counts = Counter(nick for five in last for _, nick in five)
        active = {}
        for five in last[:-1]:
            for pid, nick in sorted(five, key=lambda player: js_order(player[1])):
                if counts[nick] >= 5 and len(active) < 5:
                    active.setdefault(nick, pid)
        core = list(active.values())
        region = plurality(
            [regions.get(countries.get(p)) for p in core if countries.get(p)]
        )
        regional[region] += 1
        rows.append(
            dict(
                team=t["team"],
                core=core,
                nicks=list(active),
                points=int(t["points"] + 0.5),
                rank=len(rows) + 1,
                region=region,
                regional=regional[region],
            )
        )
    return rows


@lru_cache(maxsize=1)
def archive():
    data = history()
    first = {}
    for match in data["matches"]:
        event = match["event"]
        first[event] = min(first.get(event, match["date"]), match["date"])
    result = []
    for eid, event in data["events"].items():
        if eid not in first:
            continue
        winners = [org for org, place in event["placements"].items() if place == 1]
        result.append(
            dict(
                id=eid,
                name=event["name"],
                end=event["end"],
                winners=[
                    data["clubs"].get(org, {}).get("name", org) for org in winners
                ],
                pool=sum(event["payouts"].values()),
                lan=event["lan"],
            )
        )
    return sorted(result, key=lambda e: e["end"], reverse=True)
