"""Manual R5.3 longitudinal audit. Never run as part of the quick CI suite."""

import argparse
import json
import platform
from collections import Counter
from datetime import date
from pathlib import Path
from random import Random
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter

import psutil

from backend import (
    scout_sources,
    career,
    scouting,
    scout_reports as reports,
    skills,
    training,
)
from backend.store import Store


def metrics(c, pack):
    levels, errors, forecast_errors, widths, covered = Counter(), [], [], [], []
    costs, peaks, authors, observations, orgs = 0, [], set(), 0, set()
    counts, attempts, working_days, staffed = Counter(), Counter(), 0, 0
    by_count = {"1": [], "2–4": [], "5+": []}
    for team in [c["team"], *pack["teams"]]:
        office = scouting.org(pack, team)
        if office in orgs:
            continue
        orgs.add(office)
        club = scouting.read_club(c, pack, team)
        costs += club["cost"]
        staffed += bool(club["dossiers"])
        attempts.update(t["status"] for t in club["trials"])
        for sid, job in club["workload"].items():
            authors.add(sid)
            peaks.append(job["peak"])
            working_days += job["days"]
        levels[reports.LEVELS[0]] += len(pack["players"]) - len(club["dossiers"])
        for pid, d in club["dossiers"].items():
            view = scouting.knowledge(club, pack, c["date"], pid)
            levels[view["level"]] += 1
            observations += len(d["observations"])
            counts.update(o["source"] for o in d["observations"])
            base = pack["players"][pid]
            actual = base["skills"] | training.lookup(
                c["training"], "players", pid
            ).get("skills", {})
            ovr = skills.role_rating(actual, base["role"] or "rifler")
            lo, hi = view["current"]
            errors.append(abs((lo + hi) / 2 - ovr))
            by_count[
                "1" if view["count"] == 1 else "2–4" if view["count"] < 5 else "5+"
            ].append((errors[-1], hi - lo))
            widths.append(hi - lo)
            covered.append(lo <= ovr <= hi)
            if base["potential"] is not None:
                forecast_errors.append(
                    abs(reports.mid(view["potential"]) - base["potential"])
                )
    return dict(
        organizations=len(orgs),
        departmentsWithReports=staffed,
        sources=counts,
        trials=attempts,
        unitsPerWorkingDay=round(costs / max(1, working_days), 2),
        accuracyByObservations={
            k: dict(
                count=len(v),
                error=round(mean(x for x, _ in v), 2),
                width=round(mean(y for _, y in v), 2),
            )
            for k, v in by_count.items()
            if v
        },
        knowledgeLevels=levels,
        observations=observations,
        staff=len(authors),
        workloadUnits=costs,
        maxDailyLoad=max(peaks, default=0),
        meanOVRError=round(mean(errors), 2) if errors else None,
        meanPotentialError=round(mean(forecast_errors), 2) if forecast_errors else None,
        meanOVRWidth=round(mean(widths), 2) if widths else None,
        ovrCoverage=round(mean(covered), 3) if covered else None,
    )


def measure(years):
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "scene.sqlite"
        store = Store(path)
        pack = store.careers.pack(["austin-registration", 1])
        seed = 5303
        rng = Random(seed)
        players = pack["players"]
        # The archive has unknown ceilings. Pin a reproducible spread for the accuracy audit.
        for pid in sorted(players):
            player = players[pid]
            center = rng.randrange(48, 86)
            player.update(
                skills={
                    k: min(99, max(1, center + rng.randrange(-10, 11)))
                    for k in skills.KEYS
                },
                potential=rng.randint(center, 98),
            )
        team = next(iter(career.roster_index(pack)))
        c = career.create(
            pack, dict(team=team, scope="full", mode="owner", name="Аудит")
        )
        c["mapPool"] = ["depo"]
        c.pop("seriesProfile", None)
        c.update(week=0, queue=[])
        career.schedule(c)
        manager = next(s for s, p in pack["staff"].items() if p["team"] == team)
        c["office"]["duties"].update(dispatch=manager, search=manager)
        state = store.read()
        state["career"] = c
        initial_size = len(json.dumps(c, ensure_ascii=False).encode())
        start = date.fromisoformat(c["start"])
        elapsed = perf_counter()
        for year in range(1, years + 1):
            until = start.replace(year=start.year + year).isoformat()
            while c["date"] < until:
                day = c["date"]
                training.refresh_practices(c, pack)
                while c["queue"] and c["queue"][0]["date"] == day:
                    ev = c["queue"][0]
                    if ev["kind"] != "match":
                        c["queue"].pop(0)
                        continue
                    report = career.simulate(
                        career.initial(pack, c, ev, detailed=False)
                    )
                    store.careers.record(c, report)
                training.run_day(c, pack, day)
                c["date"] = c["training"]["nextDay"]
                if day.endswith("-01"):
                    training.freeze_day(c["training"])
                    scout_sources.freeze(c["scouting"])
            with store.transaction():
                store.write(state)
                store.careers.save(state, "1")
            store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            duration = perf_counter() - elapsed
            body = store.db.execute(
                "SELECT length(CAST(body AS BLOB)) FROM career_slot WHERE slot='1'"
            ).fetchone()[0]
            print(
                json.dumps(
                    dict(
                        year=year,
                        seed=seed,
                        python=platform.python_version(),
                        players=len(players),
                        official=len(c["history"]),
                        practices=c["training"]["fixturesPlayed"],
                        **metrics(c, pack),
                        snapshotMiB=round(body / 2**20, 3),
                        initialCareerKiB=round(initial_size / 1024, 1),
                        scoutingMiB=round(
                            len(json.dumps(c["scouting"], ensure_ascii=False).encode())
                            / 2**20,
                            3,
                        ),
                        sqliteMiB=round(path.stat().st_size / 2**20, 2),
                        rssMiB=round(psutil.Process().memory_info().rss / 2**20, 1),
                        seconds=round(duration, 2),
                        msPerDay=round(
                            duration * 1000 / (date.fromisoformat(until) - start).days,
                            2,
                        )
                    ),
                    ensure_ascii=False,
                ),
                flush=True,
            )
        store.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=5)
    measure(parser.parse_args().years)
