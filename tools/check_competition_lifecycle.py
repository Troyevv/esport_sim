"""Extended installed-map acceptance: one autonomous regional cup, checkpoints and observation."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from backend import career, competitions, cs2_maps, database, series, veto
from backend.store import Store


def command(store, kind, value=None):
    state = store.read()
    request = dict(
        id=str(uuid4()),
        kind=kind,
        value=value,
        revision=state["revision"],
        context=state["context"],
    )
    receipt = store.apply(request)
    assert store.apply(request) == receipt


def check(directory):
    assert set(veto.ACTIVE) <= set(cs2_maps.installed()), "Install the R4.1 map pack"
    path = directory / "acceptance.sqlite"
    store = Store(path)
    pack = store.careers.pack([database.RELEASE_ID, 1])
    team = next(t for t, v in pack["teams"].items() if v["name"] == "SINNERS Esports")
    command(
        store,
        "career-create",
        dict(
            id=pack["id"],
            revision=1,
            team=team,
            scope="full",
            name="Тренер",
            mode="owner",
        ),
    )
    state = store.read()
    c = state["career"]
    pack = store.careers.pack(c["source"])
    eid = "ecl-oceania-2026-4"
    event = next(e for e in competitions.season(2026) if e["id"] == eid)
    c["circuit"]["editions"][eid] = event
    c["queue"] = []
    competitions.process_day(c, pack)
    count = len(event["registrations"])
    assert count >= 3 and team not in event["registrations"]
    c["circuit"]["editions"] = {eid: event}
    c["date"] = event["lock"]
    competitions.lock(c, event, pack)
    assert all(s == "locked" for s in event["entries"].values() if s != "declined")
    store.write(state)
    command(store, "career-save", {"slot": "2"})
    command(store, "career-load", {"slot": "2"})
    fixture = store.read()["career"]["queue"][0]
    command(store, "career-watch", {"fixture": fixture["id"]})
    command(store, "career-advance")
    token, game = store.careers.work(store.read())
    assert game is None
    assert store.careers.commit_work(token, None)
    command(store, "career-play")
    observed = store.read()["world"]
    assert observed["series"]["spectator"]
    expected = career.simulate(deepcopy(observed))
    while True:
        command(store, "series-next")
        command(store, "speed", 128)
        command(store, "start")
        store.tick()
        command(store, "career-save", {"slot": "3"})
        store.db.close()
        store = Store(path)
        command(store, "career-load", {"slot": "3"})
        command(store, "start")
        while store.tick():
            pass
        game = store.read()["world"]
        if game["series"]["stage"] == "finished":
            break
    assert series.result(game) == expected
    command(store, "career-finish")
    state = store.read()
    c = state["career"]
    while c["circuit"]["editions"][eid]["status"] == "playing":
        fixture = c["queue"][0]
        game = career.initial(pack, c, fixture, detailed=False)
        report = career.simulate(game)
        with store.transaction():
            store.careers.record(c, report)
            store.write(state)
            store.careers.save(state, "auto")
        print(f"{fixture['id']} BO{fixture['bestOf']} {report['score']}", flush=True)
        state = store.read()
        c = state["career"]
    completed = c["circuit"]["editions"][eid]
    assert (
        len(c["history"]) == 2 * count - 2
        and completed["placements"][0] == c["history"][-1]["winnerTeamId"]
    )
    assert sum(c["circuit"]["awards"][eid].values()) == 2500
    assert completed["mvp"] in completed["stats"] and len(c["circuit"]["awards"]) == 1
    assert all(
        store.careers.report(r["result"])["winnerTeamId"] == r["winnerTeamId"]
        for r in c["history"]
    )
    command(store, "career-save", {"slot": "1"})
    store.db.close()
    store = Store(path)
    command(store, "career-load", {"slot": "1"})
    assert store.read()["career"]["circuit"] == c["circuit"]
    print(
        f"{completed['title']}: {len(completed['placements'])} teams, {len(c['history'])} real series, identical observed report"
    )
    store.db.close()


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        check(Path(directory))
