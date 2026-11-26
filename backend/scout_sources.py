"""Dated, player-specific evidence from verified protocols and completed exercises."""

import base64
import json
import zlib
from functools import lru_cache

from . import scout_reports as reports, skills, training


def encode(value):
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.b64encode(zlib.compress(raw, 1)).decode("ascii")


@lru_cache(maxsize=3)
def public_base(encoded):
    return json.loads(zlib.decompress(base64.b64decode(encoded))) if encoded else {}


def public_rows(state, pid):
    return state["public"].get(pid, public_base(state.get("baseline", "")).get(pid, []))


def freeze(state):
    if state["public"]:
        state["baseline"] = encode(
            public_base(state.get("baseline", "")) | state["public"]
        )
        state["public"] = {}


def save_fact(index, pid, fact):
    rows = index.setdefault(pid, [])
    if not any(r["id"] == fact["id"] for r in rows):
        rows.append(fact)
        del rows[:-4]


def performance(pack, event, stats, rounds):
    teams = [pack["teams"][t]["name"] for t in event["teams"]]
    return dict(
        id=event["id"],
        date=event["date"],
        source="practice" if event.get("pcw") else "match",
        basis=f"{teams[0]} — {teams[1]} · {rounds} р.",
        edition=event.get("edition"),
        sample=rounds,
        signals=reports.match_signals(stats, rounds),
    )


def played(c, pack, event, report):
    state = c["scouting"]
    guests = {
        r["player"]: r["host"] for r in state["trials"] if r["status"] == "active"
    }
    for s in report["stats"]:
        pid = s["player"]
        if event.get("pcw") and guests.get(pid) != s["teamId"]:
            continue
        idx = state["private"] if event.get("pcw") else state["public"]
        fact = performance(pack, event, s, len(report["rounds"]))
        if event.get("pcw"):
            fact["host"] = s["teamId"]
        if not event.get("pcw") and pid not in idx:
            idx[pid] = list(public_rows(state, pid))
        save_fact(idx, pid, fact)


def session(c, pack, team, pid, day, index, drill, grade):
    keys = [k for k in training.DRILLS[drill][4].split() if k not in skills.HIDDEN]
    if not keys:
        return
    row = training.lookup(c["training"], "players", pid)
    # A scored drill measures only the actions practiced in this session, under today's fatigue.
    signals = {
        k: reports.points(
            row.get("skills", {}).get(k, pack["players"][pid]["skills"][k])
            - row.get("fatigue", 0) / 7
            + reports.noise(pid, day, index, k) * 13
        )
        for k in keys
    }
    save_fact(
        c["scouting"]["private"],
        pid,
        dict(
            id=f"training/{team}/{day}/{index}",
            date=day,
            source="training",
            host=team,
            sample=14 + grade // 7,
            basis=training.DRILLS[drill][0],
            signals=signals,
        ),
    )


def available_facts(c, pack, team, pid, day):
    s = pack["players"][pid]["statistics"]
    facts = list(public_rows(c["scouting"], pid))
    facts.extend(f for f in c["scouting"]["private"].get(pid, []) if f["host"] == team)
    if s and s["maps"] and s["adr"] is not None:
        facts.append(
            dict(
                id="archive/" + s["event"] + "/" + s["date"],
                source="archive",
                date=s["date"],
                basis=s["event"],
                sample=min(32, s["maps"] * 12),
                signals=dict(
                    aim=reports.points(22 + 0.5 * s["adr"]),
                    positioning=reports.points(
                        47 + 18 * (s["kills"] / max(1, s["deaths"]) - 0.7)
                    ),
                ),
            )
        )
    player = pack["players"][pid]
    sample = player.get("sample")
    if sample and sample["rounds"]:
        # Team results provide weak context; usage identifies which actions were actually seen.
        win_rate = (sample["wins"] + 2) / (sample["maps"] + 4)
        base = 50 + 27 * win_rate
        fraction = sample["awpRounds"] / sample["rounds"]
        usage = sample["utilityRounds"] / sample["rounds"]
        facts.append(
            dict(
                id="sample/" + sample["until"],
                source="archive",
                date=sample["until"],
                basis=f'Публичная выборка: {sample["maps"]} карт, {sample["rounds"]} раундов',
                sample=min(40, sample["rounds"]),
                signals={
                    "coordination": reports.points(base),
                    **(
                        {"sniper_rifles": reports.points(base + 15 * fraction)}
                        if sample["awpRounds"]
                        else {}
                    ),
                    **(
                        {"support": reports.points(base + 8 * usage)}
                        if sample["utilityRounds"]
                        else {}
                    ),
                },
            )
        )
    performance = player.get("performance")
    if performance:
        facts.append(
            dict(
                id="rating/" + pack["asOf"],
                source="archive",
                date=pack["asOf"],
                basis=f'{performance["version"]} · {performance["maps"]} карт',
                sample=min(35, performance["maps"] * 4),
                signals=dict(
                    positioning=reports.points(20 + 40 * performance["rating"])
                ),
            )
        )
    return sorted(
        (f for f in facts if f["date"] <= day),
        key=lambda f: (f["date"], f["id"]),
        reverse=True,
    )


def archive_players(pack):
    global _archive_pack, _archive
    if _archive_pack is not pack:
        _archive = [
            pid
            for pid, p in pack["players"].items()
            if p["statistics"] or p.get("sample") or p.get("performance")
        ]
        _archive_pack = pack
    return _archive


_archive_pack, _archive = None, []


def assignment_archive(c, pack, task, clubs, read_report):
    """Resolve past performances for a named subject, including editions older than the public tape."""
    kind = task["kind"]
    if kind == "search":
        return {}
    wanted = set(task["target"]) if kind in ("player", "compare") else set()
    evidence = {}
    for game in reversed(c["history"]):
        if kind == "tournament":
            if game.get("edition") != task["target"]:
                continue
        elif not clubs.intersection(game["teams"]):
            continue
        protocol = read_report(game["result"])
        for row in protocol["stats"]:
            pid = row["player"]
            if (wanted and pid not in wanted) or (
                kind == "team" and row["teamId"] != task["target"]
            ):
                continue
            tape = evidence.setdefault(pid, [])
            if len(tape) < 4:
                tape.append(performance(pack, game, row, len(protocol["rounds"])))
        if wanted and all(len(evidence.get(p, [])) == 4 for p in wanted):
            break
    return evidence
