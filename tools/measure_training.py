"""Opt-in longitudinal calibration. Run as python -m tools.measure_training."""

import json
import platform
import psutil
import random
import tempfile
from datetime import date
from pathlib import Path
from statistics import mean, median, quantiles
from time import perf_counter

from backend import career, skills, training
from backend.store import Store


def distribution(values):
    values = list(values)
    cuts = quantiles(values, n=10, method="inclusive")
    return {
        k: round(v, 3)
        for k, v in zip(
            ("mean", "p10", "p50", "p90", "max"),
            (mean(values), cuts[0], median(values), cuts[8], max(values)),
        )
    }


def measure():
    rng = random.Random(5202)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "profile.sqlite")
        pack = store.careers.pack(["austin-registration", 1])
        team = next(iter(career.roster_index(pack)))
        c = career.create(
            pack, dict(name="Калибровка", mode="owner", scope="full", team=team)
        )
        c["mapPool"] = ["depo"]
        c.pop("seriesProfile", None)
        c["queue"] = []
        c["week"] = 0
        career.schedule(c)
        start = date.fromisoformat(c["date"])
        ids = sorted({p for t in c["teams"] for p in training.members(c, pack, t)})
        ages, levels = {}, {}
        for i, pid in enumerate(ids):
            base = pack["players"][pid]
            age, level = (17, 22, 29, 35)[i % 4], (40, 63, 86)[i % 3]
            ages[pid], levels[pid] = age, level
            base.update(
                born=start.replace(year=start.year - age).isoformat(),
                potential=rng.randint(max(68, level), 98),
                skills={
                    k: max(0, min(99, level + rng.randint(-8, 8))) for k in skills.KEYS
                },
            )
        c["office"]["duties"]["practice"] = next(
            k for k, v in pack["staff"].items() if v["team"] == team
        )
        results, times, fatigue = [], [], []
        count = 0
        while True:
            tick = perf_counter()
            day = c["date"]
            training.refresh_practices(c, pack)
            while c["queue"] and c["queue"][0]["date"] == day:
                event = c["queue"][0]
                if event["kind"] == "review":
                    c["queue"].pop(0)
                    continue
                report = career.simulate(career.initial(pack, c, event, detailed=False))
                training.match_practice(c, pack, event, report)
                if event.get("pcw"):
                    c["training"]["practice"].append(
                        training.practice_summary(event, report)
                    )
                    c["queue"].pop(0)
                    continue
                career.complete(
                    c, "benchmark", report["scoreByTeam"], report["winnerTeamId"]
                )
                count += 1
            training.run_day(c, pack, day)
            c["date"] = c["training"]["nextDay"]
            t = c["training"]
            fatigue.extend(v["fatigue"] for v in t["players"].values())
            times.append((perf_counter() - tick) * 1000)
            years = next(
                (
                    y
                    for y in (1, 3, 5)
                    if c["date"] == start.replace(year=start.year + y).isoformat()
                ),
                None,
            )
            if not years:
                continue
            values, changes = [], {}
            for pid in ids:
                base = pack["players"][pid]["skills"]
                current = base | t["players"][pid]["skills"]
                values.extend(current[k] for k in training.PUBLIC)
                changes[pid] = mean(current[k] - base[k] for k in training.PUBLIC)
            results.append(
                dict(
                    years=years,
                    players=len(ids),
                    official=count,
                    pcw=t["fixturesPlayed"],
                    skills=distribution(values),
                    rssMiB=round(psutil.Process().memory_info().rss / 2**20, 1),
                    at100=sum(round(x) == 100 for x in values),
                    meanSkillChange=distribution(changes.values()),
                    fatigue=distribution(fatigue),
                    growthByStartingAge={
                        age: round(mean(changes[p] for p in ids if ages[p] == age), 3)
                        for age in sorted(set(ages.values()))
                    },
                    growthByStartingLevel={
                        l: round(mean(changes[p] for p in ids if levels[p] == l), 3)
                        for l in sorted(set(levels.values()))
                    },
                    millisecondsPerDay=distribution(times),
                    seconds=round(sum(times) / 1000, 2),
                )
            )
            if years == 5:
                break
        print(
            json.dumps(
                dict(
                    seed=5202,
                    python=platform.python_version(),
                    machine=platform.machine(),
                    results=results,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    measure()
