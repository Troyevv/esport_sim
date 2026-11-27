"""Paired manual audit. Expose one scout at a time to the same verified box scores."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

from backend import (
    career,
    database,
    scout_reports,
    scout_sources,
    scouting,
    series,
    skills,
    staff,
    training,
)
from backend.store import Store


def measure(name, seed, observer_id=None):
    with TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "focus.sqlite")
        pack = store.careers.pack([database.STAFF_RELEASE, 1])
        pid = next(
            k
            for k, p in pack["players"].items()
            if p["name"].casefold() == name.casefold()
        )
        origin = scouting.membership(pack)[pid]
        team = next(
            t
            for t, p in pack["teams"].items()
            if p["name"] == "Aurora Gaming" and t != origin
        )
        c = career.create(
            pack, dict(team=team, name="Аудит", mode="owner", scope="full")
        )
        sid = observer_id or next(
            s for s, p in pack["staff"].items() if p["team"] == team
        )
        registered = set(training.members(c, pack, origin))
        opponents = sorted(
            t
            for t in c["teams"].keys() - {team, origin}
            if registered.isdisjoint(training.members(c, pack, t))
        )
        Random(seed).shuffle(opponents)
        tape = {}
        for n in range(60):
            if n % 7 not in (0, 4):
                continue
            other = opponents[len(tape)]
            day = training.offset(c["date"], n)
            event = dict(
                id=f"focus-{n}",
                kind="match",
                teams=[origin, other],
                date=day,
                seed=seed + n,
                mapId="depo",
            )
            protocol = career.simulate(career.initial(pack, c, event, detailed=False))
            expected = {
                p: t for t in event["teams"] for p in training.members(c, pack, t)
            }
            series.verify_map(
                protocol, event["teams"], expected, event["seed"], event["mapId"]
            )
            tape[n] = (event, protocol)

        base = pack["players"][pid]
        result = dict(
            player=base["name"],
            role=base["role"],
            seed=seed,
            matches=len(tape),
            runs=[],
        )
        for grade in (20, 55, 90):
            arm = deepcopy(c)
            roster = dict(pack["staff"])
            roster[sid] = dict(roster[sid], team=team, role="scout", preparation=grade)
            edition = dict(pack, staff=roster)
            scouting.change(
                arm,
                edition,
                dict(
                    action="task",
                    kind="player",
                    target=[pid],
                    author=sid,
                    priority=3,
                    days=60,
                ),
            )
            club = scouting.read_club(arm, edition, team)
            levels = []
            for n in range(60):
                day = training.offset(c["date"], n)
                arm["date"] = day
                if n in tape:
                    event, protocol = tape[n]
                    scout_sources.played(arm, edition, event, protocol)
                scouting.duty(
                    arm, edition, team, day, club, [pid], [], [], automatic=False
                )
                if n + 1 in (7, 14, 30, 60):
                    view = scouting.knowledge(club, edition, day, pid)
                    report = scouting.dossier_report(club, edition, pid, day)
                    assert (
                        report
                        and report["author"] == roster[sid]["name"]
                        and report["count"] == view["count"]
                    )
                    levels.append(
                        dict(
                            day=n + 1,
                            samples=view["count"],
                            matches=sum(
                                o["source"] == "match"
                                for o in club["dossiers"][pid]["observations"]
                            ),
                            score=view["score"],
                            current=view["current"],
                            width=view["current"][1] - view["current"][0],
                            potential=view["potential"],
                        )
                    )
            stale = []
            for gap in (30, 90, 180):
                view = scouting.knowledge(club, edition, training.offset(day, gap), pid)
                stale.append(
                    dict(
                        gap=gap,
                        score=view["score"],
                        width=view["current"][1] - view["current"][0],
                    )
                )
            person = staff.team_people(arm, edition, team)[sid]
            result["runs"].append(
                dict(
                    grade=grade,
                    ability=person["attributes"]["ability"],
                    forecast=person["attributes"]["potential"],
                    checkpoints=levels,
                    withoutAppearances=stale,
                )
            )
        # Only the offline evaluator sees the target's hidden reference, after all reports exist.
        truth = skills.role_rating(base["skills"], base["role"] or "rifler")
        for run in result["runs"]:
            for row in run["checkpoints"]:
                row["error"] = abs(scout_reports.mid(row["current"]) - truth)
                row["forecastError"] = (
                    abs(scout_reports.mid(row["potential"]) - base["potential"])
                    if base["potential"] is not None
                    else None
                )
        store.db.close()
        return result


def cohort(seed):
    # Public identity, role and registration only. Set the roster before inspecting errors.
    with TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "sample.sqlite")
        pack = store.careers.pack([database.STAFF_RELEASE, 1])
        own = next(t for t, r in pack["teams"].items() if r["name"] == "Aurora Gaming")
        roles = {}
        for pid in sorted(scouting.membership(pack)):
            player = pack["players"][pid]
            if (
                scouting.membership(pack)[pid] != own
                and player["role"] in skills.ROLE_WEIGHTS
            ):
                roles.setdefault(player["role"], []).append(player["name"])
        rng = Random(seed)
        names = [
            name
            for role in sorted(roles)
            for name in rng.sample(roles[role], min(2, len(roles[role])))
        ]
        observers = rng.sample(sorted(pack["staff"]), len(names))
        store.db.close()
    return [
        measure(n, seed + i, sid) for i, (n, sid) in enumerate(zip(names, observers))
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", default="Vexite")
    parser.add_argument("--seed", type=int, default=5303)
    parser.add_argument("--cohort", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            cohort(args.seed) if args.cohort else measure(args.player, args.seed),
            ensure_ascii=False,
            indent=2,
        )
    )
