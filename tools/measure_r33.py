"""Measure a real calendar through the first user stop in each coverage preset."""

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import psutil

from tests.reference_kernel import match
from backend import career, database
from backend.store import Store


def measure(scope, weeks):
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

        def advance():
            nonlocal peak
            command("career-advance")
            while job := store.careers.work(store.read()):
                token, game = job
                report = career.simulate(game) if game else None
                store.careers.commit_work(token, report)
                peak = max(peak, proc.memory_info().rss)

        advance()
        for week in range(weeks):
            if week:
                advance()
            command("career-play")
            command("speed", 128)
            command("start")
            while store.tick():
                pass
            command("career-finish")
            advance()
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
    args.add_argument(
        "--weeks",
        type=int,
        default=0,
        help="Число полных недель, 0 — до первого матча клуба",
    )
    options = args.parse_args()
    if options.weeks < 0:
        args.error("Число недель должно быть неотрицательным")
    for scope in options.scopes:
        measure(scope, options.weeks)
