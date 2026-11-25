"""Measure a real calendar through the first user stop in each coverage preset."""

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import psutil

from backend import career, database, match
from backend.store import Store


def measure(scope):
    with tempfile.TemporaryDirectory() as folder:
        proc = psutil.Process()
        store = Store(Path(folder) / "world.sqlite")

        def command(kind, value=None):
            state = store.read()
            store.apply(
                dict(
                    id=str(uuid4()),
                    revision=state["revision"],
                    context=state["context"],
                    kind=kind,
                    value=value,
                )
            )

        pack = store.careers.pack([database.RELEASE_ID, 1])
        team = next(
            k for k, t in pack["teams"].items() if "vitality" in t["name"].lower()
        )
        command(
            "career-create",
            dict(
                id=pack["id"],
                revision=1,
                team=team,
                mode="manager",
                name="Замер",
                regions=["Asia"],
                scope=scope,
            ),
        )
        started = time.perf_counter()
        peak = proc.memory_info().rss
        command("career-advance")
        while job := store.careers.work(store.read()):
            token, game = job
            report = career.simulate(game) if game else None
            store.careers.commit_work(token, report)
            peak = max(peak, proc.memory_info().rss)
        c = store.read()["career"]
        print(
            json.dumps(
                dict(
                    scope=scope,
                    edition=c["source"],
                    teams=len(c["teams"]),
                    matches=len(c["history"]),
                    firstSeed=c["history"][0]["seed"],
                    days=(database.day(c["date"]) - database.day(c["start"])).days,
                    seconds=round(time.perf_counter() - started, 2),
                    sampledPeakMiB=round(peak / 2**20),
                    rules=match.VERSION,
                    python=platform.python_version(),
                    machine=platform.machine(),
                )
            ),
            flush=True,
        )
        store.db.close()
        store.badges.close()
        store.portraits.close()


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("scopes", nargs="*", default=list(career.SCOPES))
    for scope in args.parse_args().scopes:
        measure(scope)
