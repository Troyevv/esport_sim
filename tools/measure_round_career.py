"""Manual, full-scene calendar benchmark using production fixtures, storage and decisions."""

import argparse
import json
import platform
from collections import defaultdict
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

from backend import attention, career, competitions, database
from backend.store import Store


def measure(path, days, compare=None, reports=None):
    store = Store(path)
    pack = store.careers.pack([database.STAFF_RELEASE, 1])
    team = next(t for t, r in pack["teams"].items() if r["name"] == "Aurora Gaming")

    def command(state, kind, value=None):
        store.apply(
            dict(
                kind=kind,
                value=value,
                id=str(uuid4()),
                context=state["context"],
                revision=state["revision"],
            )
        )

    command(
        store.read(),
        "career-create",
        dict(
            id=pack["id"],
            revision=1,
            mode="owner",
            scope="full",
            team=team,
            name="Aurora",
        ),
    )
    if compare:
        league = "ecl-eu-2026-13"
        command(
            store.read(),
            "career-entry",
            dict(action="prioritise", edition=league, release=["pgl-major-2026"]),
        )
        c = store.read()["career"]
        command(
            store.read(),
            "career-entry",
            dict(
                action="submit",
                edition=league,
                players=pack["rosters"][c["teams"][team]]["players"],
                reserves=[],
                coach=None,
            ),
        )
        command(store.read(), "career-save", dict(slot="2"))
        command(store.read(), "career-load", dict(slot="2"))
    sample = []
    times = defaultdict(float)
    per_match, per_day = [], defaultdict(float)

    child_cost = []

    def timed(key, func):
        def call(*args, **kwargs):
            child_cost.append(0.0)
            start = perf_counter()
            try:
                result = func(*args, **kwargs)
            finally:
                elapsed = perf_counter() - start
                times[key] += elapsed - child_cost.pop()
                if child_cost:
                    child_cost[-1] += elapsed
            if key == "rounds":
                per_match.append(elapsed)
            return result

        return call

    with ExitStack() as stack:
        if compare == "detailed":
            original = career.initial

            def detailed(*args, **kwargs):
                return original(*args, **(kwargs | {"detailed": True}))

            stack.enter_context(patch.object(career, "initial", detailed))
        for obj, name, key in [
            (store, "read", "readCheckpoint"),
            (store, "write", "writeCheckpoint"),
            (store.careers, "save", "saveSlot"),
            (competitions, "publish", "VRS"),
            (competitions, "completed", "calendar"),
            (competitions, "tick", "calendar"),
            (competitions, "settle_fixture_conflicts", "calendar"),
            (competitions, "resolve_availability", "calendar"),
            (attention, "blockers", "calendar"),
            (store.careers, "record", "validateAndStoreReport"),
            (career, "initial", "input"),
            (career, "simulate", "rounds"),
        ]:
            stack.enter_context(patch.object(obj, name, timed(key, getattr(obj, name))))
        start = perf_counter()
        while True:
            step = perf_counter()
            state = store.read()
            c = state["career"]
            if (
                date.fromisoformat(c["date"]) - date.fromisoformat(c["start"])
            ).days >= days:
                break
            if not c["progress"]:
                assert not c["error"], c["error"]
                rows = attention.blockers(
                    c, store.careers.pack(c["source"]), state["world"]
                )
                if not rows:
                    command(state, "career-advance")
                elif rows[0]["action"] == "play":
                    command(state, "career-quick", dict(fixture=c["queue"][0]["id"]))
                else:
                    command(
                        state,
                        "career-entry",
                        dict(action="leave", edition=rows[0]["edition"]),
                    )
            else:
                token, game = store.careers.work(state)
                report = career.simulate(game) if game else None
                if compare:
                    assert store.careers.commit_work(token, report)
                    if report:
                        sample.append(report)
                else:
                    assert store.careers.commit_batch(token, report)
            per_day[c["date"]] += perf_counter() - step
        wall = perf_counter() - start
    times["remainingServiceAndTransactions"] = wall - sum(times.values())
    print(
        json.dumps(
            dict(
                platform=platform.platform(),
                python=platform.python_version(),
                date=c["date"],
                days=days,
                elapsed=wall,
                teams=len(c["teams"]),
                series=len(c["history"]),
                practiceMaps=c["training"]["fixturesPlayed"],
                simulationsTimed=len(per_match),
                matchesInHistory=len(c["history"]),
                finished=sum(
                    e["status"] == "finished" for e in c["circuit"]["editions"].values()
                ),
                awards=len(c["circuit"]["awards"]),
                medianDay=median(per_day.values()),
                p95Day=quantiles(per_day.values(), n=20, method="inclusive")[-1]
                if len(per_day) > 1
                else wall,
                meanSimulationMs=1000 * sum(per_match) / len(per_match),
                maxSimulationMs=1000 * max(per_match),
                seconds=times,
                sqliteMiB=path.stat().st_size / 2**20,
            ),
            indent=2,
        )
    )
    if reports and compare:
        reports.write_text(json.dumps(dict(times=times, samples=sample)))
    store.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument(
        "--compare",
        choices=["detailed", "round"],
        help="Same 13 Aurora fixtures across the first day boundary",
    )
    parser.add_argument(
        "--reports", type=Path, help="Write the comparison sample for calibration"
    )
    opts = parser.parse_args()
    with TemporaryDirectory() as tmp:
        measure(
            Path(tmp) / "season.sqlite",
            1 if opts.compare else opts.days,
            opts.compare,
            opts.reports,
        )
