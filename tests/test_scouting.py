from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import (
    career,
    match,
    scout_reports as r,
    scouting as sc,
    skills,
    staff,
    training,
)
from backend.server import create_app
from backend.store import Store, Conflict


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPORT_SIM_MAPS", str(tmp_path / "absent"))
    store = Store(tmp_path / "career.sqlite")
    pack = store.careers.pack(["austin-registration", 1])
    team = next(t for t, row in pack["teams"].items() if row["name"] == "Vitality")
    command(
        store,
        "career-create",
        dict(
            id=pack["id"],
            revision=1,
            team=team,
            name="Аудит",
            mode="owner",
            scope="full",
        ),
    )
    yield store, pack, store.read()["career"]
    store.db.close()


def intent(store, kind, value):
    s = store.read()
    return dict(
        id=str(uuid4()),
        kind=kind,
        value=value,
        context=s["context"],
        revision=s["revision"],
    )


def command(store, kind, value=None):
    return store.apply(intent(store, kind, value))


def test_opinions_accuracy_decay_and_no_report_from_a_timer(game):
    _, pack, c = game
    player = next(iter(pack["players"]))

    def opinions(grade):
        person = dict(
            id=str(grade),
            name="Автор",
            attributes=dict(ability=grade, potential=grade, discovery=grade, fit=grade),
        )
        # Controlled observable scores isolate the observer's error from match variance.
        return [
            r.observation(
                dict(
                    id=str(i),
                    basis="Протокол",
                    source="match",
                    date=c["date"],
                    sample=26,
                    signals=dict(aim=65, positioning=72),
                ),
                person,
                70,
                True,
            )
            for i in range(55)
        ]

    precise, weak = opinions(95), opinions(15)
    good = r.assessment(precise, c["date"])
    bad = r.assessment(weak, c["date"])
    assert good["skills"] != bad["skills"] and good["potential"] != bad["potential"]
    assert sum(abs(o["values"]["aim"] - 65) for o in precise) < sum(
        abs(o["values"]["aim"] - 65) for o in weak
    )

    def width(v):
        return v["current"][1] - v["current"][0]

    assert width(good) < width(bad) and width(good) < width(
        r.assessment(precise[:2], c["date"])
    )
    assert {r.assessment(precise[:n], c["date"])["level"] for n in range(56)} == set(
        r.LEVELS
    )
    future = training.offset(c["date"], 160)
    stale = r.assessment(precise[:10], future)
    updated = r.assessment(precise[:10] + [dict(precise[11], date=future)], future)
    assert (
        stale["score"] < r.assessment(precise[:10], c["date"])["score"]
        and updated["score"] > stale["score"]
    )
    unknown = next(p for p, v in pack["players"].items() if not v["statistics"])
    sc.change(
        c,
        pack,
        dict(
            action="task",
            kind="player",
            target=[unknown],
            author=None,
            priority=3,
            days=3,
        ),
    )
    for n in range(4):
        sc.daily(c, pack, training.offset(c["date"], n))
    d = sc.center(c, pack)
    assert (
        d["tasks"][0]["status"] == "complete"
        and d["reports"] == []
        and "knowledge" not in d["players"][unknown]
    )


def test_assigned_reports_and_shared_staff_capacity(game):
    _, pack, c = game
    team, day = c["team"], c["date"]
    sid = next(iter(staff.team_people(c, pack, team)))
    pid = next(p for p, v in pack["players"].items() if v["statistics"])
    for author in [sid, "@manager-" + team, sid]:
        sc.change(
            c,
            pack,
            dict(
                action="task",
                kind="player",
                target=[pid],
                author=author,
                priority=2,
                days=7,
            ),
        )
    sc.daily(c, pack, day)
    club = sc.read_club(c, pack, team)
    history = club["dossiers"][pid]
    assert len(history["observations"]) == 2
    assert len({o["author"] for o in history["observations"]}) == 2
    first = sc.dossier_report(club, pack, pid, day, 1)
    second = sc.dossier_report(club, pack, pid, day, 2)
    assert first["author"] != second["author"] and first["current"] != second["current"]
    assert first == sc.dossier_report(club, pack, pid, training.offset(day, 200), 1)
    staff.change(c, pack, dict(duty="dispatch", person=sid))
    # A fully booked dispatcher cannot give a new assignment or spend more workload.
    sc.change(
        c,
        pack,
        dict(
            action="task", kind="player", target=[pid], author=None, priority=3, days=5
        ),
    )
    nextday = training.offset(day, 1)
    capacity = staff.capacity(staff.team_people(c, pack, team)[sid])
    staff.record(
        c,
        [
            dict(
                person=sid,
                team=team,
                date=nextday,
                duty="veto",
                cost=capacity,
                event="series",
            )
        ],
        nextday,
    )
    sc.daily(c, pack, nextday)
    assert club["tasks"][-1]["author"] is None
    assert (
        sum(j["cost"] for j in c["office"]["ledger"]["jobs"] if j["person"] == sid)
        == capacity
    )
    sc.daily(c, pack, training.offset(day, 2))
    assert club["tasks"][-1]["author"] and club["dispatchCost"] > 0


@pytest.mark.parametrize("duration", [3, 7, 14])
def test_trial_is_temporary_observed_and_not_registered(game, duration):
    store, pack, c = game
    host, day = c["team"], c["date"]
    ids = list(training.members(c, pack, host))
    p = next(
        p
        for p in pack["players"]
        if p not in ids and r.noise(p, host, day, "player") > -0.65
    )
    pack["players"][p]["contract"] = "free"
    sc._indexed_pack = None
    club = sc.read_club(c, pack, host)
    trial = sc.invite(c, pack, host, p, day, duration, club)
    assert trial["status"] == "active" and trial["permission"] is None
    official = deepcopy(next(e for e in c["queue"] if host in e["teams"]))
    away = next(
        t for t in c["teams"] if t != host and p not in training.members(c, pack, t)
    )
    ev = training.fixture(c, day, host, away, "depo", "attack", True, 0)
    c["queue"].insert(0, ev)
    watched = career.initial(pack, c, ev)
    assert p in watched["domain"]["players"]
    projected = match.project(watched, "full")["match"]
    guest = next(a["id"] for a in watched["agents"] if a["playerId"] == p)
    assert guest not in projected["roleRatings"] and projected["teamRating"] is None
    result = career.simulate(career.initial(pack, c, ev, detailed=False))
    store.careers.record(c, result)
    assert any(s["player"] == p for s in result["stats"]) and not c["history"]
    assert p not in career.match_domain(pack, c, official)[0]["managerPlayers"]
    c["training"]["plans"][day] = [dict(kind="mechanics")]
    for i in range(duration):
        stamp = training.offset(day, i)
        c["training"]["plans"][stamp] = [dict(kind="mechanics")]
        training.run_day(c, pack, stamp)
    dossier = sc.read_club(c, pack, host)["dossiers"][p]
    assert {o["source"] for o in dossier["observations"]} >= {"training", "practice"}
    assert trial["status"] == "finished" and trial["report"]
    assert (
        sc.dossier_report(
            sc.read_club(c, pack, host), pack, p, trial["end"], trial["report"]
        )["trialObservations"]
        >= 2
    )
    assert (
        training.members(c, pack, host) == ids
        and p not in sc.practice_rosters(c, pack, ev)[host]
    )
    assert p not in c["training"]["weekStats"].get(day, {})
    assert p not in c["training"]["days"][day]["metrics"]


def test_permission_refusal_and_fixture_conflicts(game):
    _, pack, c = game
    host, day = c["team"], c["date"]
    origin = sc.membership(pack)
    ids = [p for p, t in origin.items() if t != host]
    club = sc.read_club(c, pack, host)
    for desired in ("declined", "blocked", "active"):
        p = next(
            p
            for p in ids
            if (
                "declined"
                if r.noise(p, host, day, "player") <= -0.65
                else (
                    "blocked"
                    if r.noise(origin[p], host, p, day, "club") <= -0.35
                    else "active"
                )
            )
            == desired
        )
        t = sc.invite(c, pack, host, p, day, 7, club)
        assert t["status"] == desired
    assert p not in sc.attendance(c, pack, day, {t["origin"]})
    assert p in sc.attendance(c, pack, day, set())
    with pytest.raises(ValueError):
        sc.invite(c, pack, host, p, day, 14, club)


def test_old_slots_receipts_and_ai_isolation(game):
    s, pack, c = game
    pid = next(p for p, x in pack["players"].items() if x["statistics"])
    cmd = intent(
        s,
        "career-scouting",
        dict(action="task", kind="player", target=[pid], priority=2, days=21),
    )
    result = s.apply(cmd)
    assert s.apply(cmd) == result
    with pytest.raises(Conflict):
        s.apply(dict(cmd, id=str(uuid4())))
    state = s.read()
    assert len(sc.center(state["career"], pack)["tasks"]) == 1
    old = deepcopy(state)
    old["career"].pop("scouting")
    with s.transaction():
        s.write(old)
        for slot in ("auto", "1"):
            s.careers.save(old, slot)
    restarted = Store(Path(s.db.execute("PRAGMA database_list").fetchone()[2]))
    try:
        assert restarted.read()["career"]["scouting"] == sc.new()
        for slot in ("auto", "1"):
            command(restarted, "career-load", dict(slot=slot))
            assert restarted.read()["career"]["scouting"] == sc.new()
        assert (
            restarted.db.execute("SELECT count(*) FROM checkpoint_backup").fetchone()[0]
            >= 3
        )
        command(restarted, "career-advance")
        while job := restarted.careers.work(restarted.read()):
            token, game = job
            report = career.simulate(game) if game else None
            assert restarted.careers.commit_work(token, report)
            assert not restarted.careers.commit_work(token, report)
        fresh = restarted.read()["career"]
        assert sc.center(fresh, pack)["reports"] == []
        assert any(
            sc.read_club(fresh, pack, t)["dossiers"]
            for t in fresh["teams"]
            if t != c["team"]
        )
        command(restarted, "career-save", dict(slot="1"))
        command(restarted, "career-load", dict(slot="1"))
        assert restarted.read()["career"]["scouting"] == fresh["scouting"]
    finally:
        restarted.db.close()


def test_career_api_disclosure_and_noninterference(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPORT_SIM_MAPS", str(tmp_path / "absent"))
    app = create_app(tmp_path / "api.sqlite")
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        s = app.state.store
        pack = s.careers.pack(["austin-registration", 1])
        team = next(iter(career.roster_index(pack)))
        command(
            s,
            "career-create",
            dict(
                id=pack["id"],
                revision=1,
                team=team,
                name="Проверка",
                scope="full",
                mode="owner",
            ),
        )
        c = s.read()["career"]
        pid = next(
            p
            for p, row in pack["players"].items()
            if p not in training.members(c, pack, team) and row["statistics"]
        )
        command(
            s,
            "career-scouting",
            dict(action="task", kind="player", target=[pid], days=3, priority=3),
        )
        state = s.read()
        sc.daily(state["career"], pack, c["date"])
        with s.transaction():
            s.write(state)
        # Private PCW schedules and box scores belong to participating clubs.
        away = [t for t in pack["teams"] if t != team][:2]
        fixture = dict(
            id="private-pcw", date=c["date"], teams=away, pcw=True, kind="match"
        )
        state["career"]["training"]["practice"].append(
            dict(fixture, result="private-digest")
        )
        state["career"]["queue"].append(fixture)
        with s.transaction():
            s.write(state)
        assert client.get("/api/career/report/private-pcw").status_code == 404
        assert fixture not in client.get("/api/career").json()["active"]["queue"]
        root = "/api/career/" + c["id"]
        paths = [
            "/api/state",
            "/api/career",
            root + "/scene",
            root + "/scouting",
            root + "/scouting/" + pid,
            root + "/scouting/" + pid + "/1",
            root + "/training?week=" + c["date"],
            "/api/tactics",
        ]

        def read():
            values = []
            for path in paths:
                resp = client.get(path)
                assert resp.status_code == 200, (path, resp.text)
                values.append(resp.json())
            return values

        before = read()
        assert not set(before[4]["skills"]) & skills.HIDDEN
        assert isinstance(before[4]["potential"], list)
        assert client.get(root + "/scouting/" + pid + "/999").status_code == 404
        assert client.get("/api/database/austin-registration/1").status_code == 409
        assert (
            client.get("/api/database/austin-registration/1/ratings/" + pid).status_code
            == 409
        )
        # Edit server truth only. Every user-facing DTO and every estimated search stays identical.
        filters = [
            {},
            {"current": 60},
            {"potential": 75},
            {"skill": "aim", "minimum": 50},
        ]
        club = sc.read_club(state["career"], pack, team)

        def result_sets():
            return [
                [
                    p
                    for p in pack["players"]
                    if sc.candidates(club, pack, c["date"], p, f)
                ]
                for f in filters
            ]

        results = result_sets()
        for p in pack["players"].values():
            p["potential"] = 99
        pack["players"][pid]["skills"] = dict.fromkeys(skills.KEYS, 1)
        assert read() == before and result_sets() == results


def test_incoming_club_permission_and_archive_isolation(game):
    store, pack, c = game
    day, host = c["date"], c["team"]
    other = next(t for t in c["teams"] if t != host)
    own = training.members(c, pack, host)
    player = next(p for p in own if r.noise(p, other, day, "player") > -0.65)
    club = sc.read_club(c, pack, other)
    invitation = sc.invite(c, pack, other, player, day, 7, club)
    sc.write_club(c, pack, other, club)
    assert invitation["status"] == "requested" and not sc.attendance(
        c, pack, day, set()
    )
    assert sc.center(c, pack)["incoming"] == [invitation]
    sc.change(c, pack, dict(action="permit", id=invitation["id"]))
    assert sc.attendance(c, pack, day, set()) == {player: other}
    assert not sc.attendance(c, pack, day, {host})
    assert sc.center(c, pack)["reports"] == []
    with pytest.raises(ValueError):
        sc.change(c, pack, dict(action="deny", id=invitation["id"]))

    ev = next(e for e in c["queue"] if host in e["teams"])
    c["queue"].remove(ev)
    c["queue"].insert(0, ev)
    result = career.simulate(career.initial(pack, c, ev, detailed=False))
    store.careers.record(c, result)
    c["history"][-1]["edition"] = "completed-cup"
    c["circuit"] = {"editions": {"completed-cup": {"title": "Архивный турнир"}}}
    # Evict it from the rolling tape. A tournament assignment can still read its verified protocol.
    c["scouting"]["public"] = {}
    sc.change(
        c,
        pack,
        dict(
            action="task", kind="tournament", target="completed-cup", days=4, priority=2
        ),
        store.careers.report,
    )
    sc.daily(c, pack, c["date"])
    view = sc.center(c, pack)
    assert "archive" not in view["tasks"][-1] and len(view["tasks"][-1]["results"]) == 1
    pid = view["tasks"][-1]["results"][0]
    report = sc.dossier_report(sc.read_club(c, pack, host), pack, pid, c["date"])
    assert report["evidence"][0]["event"] == ev["id"]
    other_club = sc.read_club(c, pack, other)
    assert all(t["id"] != view["tasks"][-1]["id"] for t in other_club["tasks"])
    assert all(
        o["name"] != report["author"]
        for d in other_club["dossiers"].values()
        for o in d["observations"]
    )


def test_active_bulk_rolls_back_and_slots_restore_independent_archives(game):
    s, pack, c = game
    state = s.read()
    for i in range(7):
        sc.daily(state["career"], pack, training.offset(c["date"], i))
    with s.transaction():
        s.write(state)
        s.careers.save(state, "2")
    expected = s.read()["career"]["scouting"]
    assert expected["clubs"]
    with pytest.raises(RuntimeError):
        with s.transaction():
            altered = s.read()
            altered["career"]["scouting"]["clubs"] = {}
            altered["career"]["scouting"]["baseline"] = sc.sources.encode({})
            s.write(altered)
            raise RuntimeError("rollback")
    assert s.read()["career"]["scouting"] == expected
    command(s, "career-load", dict(slot="2"))
    assert s.read()["career"]["scouting"] == expected


def test_context_uses_rounds_and_public_peers_without_inventing_skills(game):
    from backend import scout_sources

    _, pack, c = game
    teams = list(c["teams"])[:2]
    pid = training.members(c, pack, teams[0])[0]
    event = dict(id="series", date=c["date"], teams=teams)
    row = dict(
        player=pid,
        teamId=teams[0],
        k=15,
        d=10,
        a=6,
        damage=1450,
        opening=3,
        openingDeaths=2,
        hs=8,
        kast=16,
    )
    # The aggregate map score says little about the distribution of rounds.
    protocol = dict(
        scoreByTeam={teams[0]: 2, teams[1]: 1},
        rounds=[dict(winnerTeamId=t) for t in [teams[0]] * 30 + [teams[1]] * 20],
        stats=[row],
    )
    context = scout_sources.competition_context(pack, event, protocol)
    opposite = dict(
        protocol,
        rounds=[dict(winnerTeamId=t) for t in [teams[0]] * 20 + [teams[1]] * 30],
    )
    assert (
        context[teams[0]]["reference"]
        > scout_sources.competition_context(pack, event, opposite)[teams[0]][
            "reference"
        ]
    )
    changed = dict(
        pack, teams={**pack["teams"], teams[1]: dict(pack["teams"][teams[1]], tier=1)}
    )
    weak = dict(
        pack, teams={**pack["teams"], teams[1]: dict(pack["teams"][teams[1]], tier=3)}
    )
    assert (
        scout_sources.competition_context(changed, event, protocol)[teams[0]][
            "reference"
        ]
        > scout_sources.competition_context(weak, event, protocol)[teams[0]][
            "reference"
        ]
    )
    a, level = r.performance_signals(row, 50, "entry", context[teams[0]])
    assert level != r.performance_signals(row, 50, "support", context[teams[0]])[1]
    assert "calling" not in a and "sniper_rifles" not in a
    person = next(iter(sc.observers(c, pack, c["team"]).values()))
    fact = dict(
        id="rating",
        source="archive",
        date=c["date"],
        basis="Rating",
        sample=35,
        maps=132,
        signals={},
        level=70,
    )
    obs = r.observation(fact, person, 50, True)
    view = r.assessment([obs], c["date"])
    assert view["skills"] == {} and view["current"] and view["score"] < 38
    assert obs["weight"] > obs["exposure"]
    assert r.describe(view, pack["players"][pid], [obs], [], [])["strength"] is None


def test_delegated_screening_follows_active_subject_without_timer_reports(game):
    _, pack, c = game
    team = c["team"]
    pid = next(p for p, t in sc.membership(pack).items() if t != team)
    club = sc.department()
    search = sc.make_task(c, c["date"], "search", None, {}, None, 1, 14)
    search.update(status="complete", results=[pid])
    club["tasks"].append(search)
    c["scouting"]["public"][pid] = [dict(date=c["date"])]
    sc.plan_department(c, pack, team, club, c["date"])
    task = club["tasks"][-1]
    assert task["kind"] == "player" and task["target"] == [pid]
    assert task["due"] == training.offset(c["date"], 41)
    assert not club["dossiers"]


def test_same_tape_replays_without_foreign_truth_and_preserves_old_opinion(game):
    _, pack, c = game
    team = c["team"]
    pid = next(pid for pid in pack["players"] if not sc.employed(c, pack, team, pid))
    person = next(iter(sc.observers(c, pack, team).values()))
    fact = dict(
        id="verified",
        date=c["date"],
        source="match",
        basis="Протокол",
        sample=24,
        signals={"entry": 68, "aim": 75},
        level=72,
        rawLevel=59,
        context=True,
    )
    player = pack["players"][pid]
    altered = dict(
        pack,
        players={
            **pack["players"],
            pid: dict(player, skills=dict.fromkeys(skills.KEYS, 0), potential=100),
        },
    )

    def evaluate(edition):
        club = sc.department()
        sc.record_observation(
            deepcopy(c), edition, team, club, pid, person, fact, c["date"]
        )
        dossier = club["dossiers"][pid]
        current = sc.dossier_report(club, edition, pid, c["date"], 1)
        # Published reports from the first PR keep their original scoring formula.
        dossier["versions"][0].pop("model")
        old = sc.dossier_report(club, edition, pid, c["date"], 1)
        assert (
            old["current"]
            == r.assessment(
                dossier["observations"],
                c["date"],
                player["born"],
                player["role"],
                model=1,
            )["current"]
        )
        return current

    assert evaluate(pack) == evaluate(altered)


def test_calendar_checkpoint_rejects_concurrent_change_and_retry(game):
    store, _, c = game
    command(store, "career-advance")
    prepared = store.calendar_checkpoint()
    token, world = store.careers.work(prepared[1])
    report = career.simulate(world) if world else None
    # A second writer commits while the simulation works outside the calendar lock.
    latest = store.read()
    latest["career"]["milestones"].append(dict(title="Поступивший отчёт", date=c["date"]))
    with store.transaction():
        store.write(latest)
    assert not store.careers.commit_batch(token, report, prepared=prepared)
    assert store.read()["career"]["milestones"][-1]["title"] == "Поступивший отчёт"
    fresh = store.calendar_checkpoint()
    token, world = store.careers.work(fresh[1])
    report = career.simulate(world) if world else None
    assert store.careers.commit_batch(token, report, prepared=fresh)
    assert not store.careers.commit_batch(token, report, prepared=fresh)
