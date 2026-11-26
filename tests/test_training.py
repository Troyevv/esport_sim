from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from backend import (
    attention,
    career,
    database,
    match,
    skills,
    staff,
    tactics,
    training,
    training_center,
)
from backend.store import Store


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPORT_SIM_MAPS", str(tmp_path / "maps"))
    s = Store(tmp_path / "career.sqlite")
    pack = s.careers.pack(["austin-registration", 1])
    team = next(t for t, r in pack["teams"].items() if r["name"] == "Vitality")
    command(
        s,
        "career-create",
        dict(
            id=pack["id"],
            revision=1,
            team=team,
            name="Тренер",
            mode="owner",
            scope="full",
        ),
    )
    yield s, pack
    s.db.close()


def intent(s, kind, value):
    state = s.read()
    return dict(
        id=str(uuid4()),
        context=state["context"],
        revision=state["revision"],
        kind=kind,
        value=value,
    )


def command(s, kind, value=None):
    return s.apply(intent(s, kind, value))


def advance(s):
    command(s, "career-advance")
    while job := s.careers.work(s.read()):
        token, game = job
        result = career.simulate(game) if game else None
        assert s.careers.commit_work(token, result)
        assert not s.careers.commit_work(token, result)


def test_load_program_specialist_limits_and_effects(office):
    s, pack = office
    c = s.read()["career"]
    team, day, t = c["team"], c["date"], c["training"]
    pid, other, *_ = training.members(c, pack, team)
    specialist = next(iter(staff.team_people(c, pack, team)))
    program = dict(
        action="program",
        player=pid,
        role="igl",
        skills=["aim"],
        maps=["depo"],
        intensity=1.25,
        coach=specialist,
    )
    training_center.change(c, pack, s.db, program)
    with pytest.raises(ValueError):
        training_center.change(c, pack, s.db, program | {"skills": ["learning"]})
    row = dict(action="session", date=day, kind="program", player=pid, index=0)
    t["plans"][day] = []
    training_center.change(c, pack, s.db, row)
    training_center.change(c, pack, s.db, row | {"index": 1})
    with pytest.raises(ValueError, match="нагрузк"):
        training_center.change(c, pack, s.db, row | {"index": 2})
    # Compare the same two lessons with the instructor already booked.
    occupied = deepcopy(c)
    p = staff.team_people(c, pack, team)[specialist]
    staff.record(
        occupied,
        [
            dict(
                team=team,
                date=day,
                person=specialist,
                duty="veto",
                event="booking",
                cost=staff.capacity(p),
            )
        ],
        day,
    )
    for club in [c, occupied]:
        training.run_day(club, pack, day)
    a, b = (training.lookup(club["training"], "players", pid) for club in (c, occupied))
    assert a["skills"]["aim"] > b["skills"]["aim"]
    assert (
        set(a["skills"]) == {"aim"}
        and a["roleMastery"]["igl"] > pack["players"][pid]["roleMastery"]["igl"]
    )
    assert a["mapKnowledge"]["depo"] > pack["players"][pid]["mapKnowledge"]["depo"]
    assert a["fatigue"] > training.lookup(t, "players", other)["fatigue"]
    assert len(t["players"]) == 60
    for k, default in (("skills", {}), ("roleMastery", {})):
        assert training.lookup(t, "players", other)[k] == default
    assert (
        t["days"][day]["sessions"][0]["specialist"]
        and not occupied["training"]["days"][day]["sessions"][0]["specialist"]
    )
    public = training_center.week(c, pack, s.db, day)
    assert skills.HIDDEN.isdisjoint(public["players"][pid]["skills"])
    assert "potential" not in public["players"][pid]
    before = a["fatigue"]
    next_day = t["nextDay"]
    t["plans"][next_day] = [dict(kind="recovery")]
    training.run_day(c, pack, next_day)
    assert a["fatigue"] < before
    assert t["days"][next_day]["metrics"][pid]["recovery"] > 0


def test_week_template_limits_and_staff_planner(office):
    s, pack = office
    c = s.read()["career"]
    first = training.monday(c["date"])
    t = c["training"]
    day = c["date"]
    t["plans"][day] = [dict(kind="utility"), dict(kind="mental")]
    training_center.change(
        c, pack, s.db, dict(action="template", name="Неделя", date=first)
    )
    later = training.offset(first, 7)
    training_center.change(
        c, pack, s.db, dict(action="apply", name="Неделя", date=later)
    )
    assert t["plans"][training.offset(day, 7)] == t["plans"][day]
    target = next(e for e in c["queue"] if c["team"] in e["teams"])
    with pytest.raises(ValueError, match="официальной"):
        training_center.change(
            c,
            pack,
            s.db,
            dict(action="session", kind="mechanics", index=0, date=target["date"]),
        )
    people = staff.team_people(c, pack, c["team"])
    sid = next(iter(people))
    staff.change(c, pack, dict(person=sid, duty="schedule"))
    training_center.change(c, pack, s.db, dict(action="auto", date=day))
    training.run_day(c, pack, day)
    assert any(
        j["duty"] == "schedule" and j["person"] == sid
        for j in c["office"]["ledger"]["jobs"]
    )
    assert sum(
        j["cost"] for j in c["office"]["ledger"]["jobs"] if j["person"] == sid
    ) <= staff.capacity(people[sid])


@pytest.mark.parametrize("watch", [False, True])
def test_pcw_runs_existing_kernel_once_across_slots(office, watch):
    s, pack = office
    c = s.read()["career"]
    other = next(t for t in c["teams"] if t != c["team"])
    board = tactics.standards()[0]
    request = intent(
        s,
        "career-training",
        dict(
            action="pcw",
            date=c["date"],
            opponent=other,
            map="depo",
            games=2,
            goal="attack",
            watch=watch,
            tactic=board,
        ),
    )
    assert s.apply(request) == s.apply(request)
    state = s.read()
    ev = state["career"]["queue"][0]
    assert ev["pcw"]
    assert [e["teams"][0] for e in state["career"]["queue"] if e.get("pcw")] == [
        c["team"],
        other,
    ]
    if watch:
        assert (
            attention.blockers(state["career"], pack, state["world"])[0]["action"]
            == "play"
        )
        command(s, "career-play")
        game = s.read()["world"]
        assert game["playbook"][board["side"] + "/" + board["buy"]]["id"] == board["id"]
        command(s, "speed", 128)
        command(s, "start")
        while s.tick():
            pass
        command(s, "career-finish")
    else:
        assert not attention.blockers(state["career"], pack, state["world"])
        command(s, "career-advance")
        token, game = s.careers.work(s.read())
        report = career.simulate(game)
        assert s.careers.commit_work(token, report)
        assert not s.careers.commit_work(token, report)
    state = s.read()
    actual = state["career"]["training"]["practice"][0]
    raw = s.careers.report(actual["result"])
    calls = [
        row for row in raw["rounds"] if row.get("tactic") == tactics.reference(board)
    ]
    assert calls and all(row["round"] in (1, 13) for row in calls)
    assert actual["rounds"] == len(raw["rounds"]) == sum(actual["score"])
    assert actual["simulation"]["mode"] == ("detailed" if watch else "round")
    assert not state["career"]["history"] and len(actual["stats"]) == 10
    pid = training.members(c, pack, c["team"])[0]
    assert (
        training.lookup(state["career"]["training"], "players", pid)["tactics"][
            training.tactic_key(board)
        ]
        > 0
    )
    command(s, "career-save", {"slot": "2"})
    command(s, "career-load", {"slot": "2"})
    assert s.read()["career"]["training"] == state["career"]["training"]


def test_study_changes_step_timing_and_survives_immutable_checkpoint(office):
    s, pack = office
    c = s.read()["career"]
    team = c["team"]
    board = tactics.standards()[0]
    other = next(t for t in c["teams"] if t != team)
    ev = training.fixture(c, c["date"], team, other, "depo", "attack", True, 0)
    t = c["training"]
    timing = []
    for learned in (0, 95):
        for pid in training.members(c, pack, team):
            training.player(t, pid)["tactics"][training.tactic_key(board)] = learned
        training.freeze_day(t)
        game = career.initial(pack, c, ev)
        match.assign(game, board)
        while game["tick"] < 280:
            match.advance(game)
        timing.append(
            [
                (e["actor"] if "actor" in e else e.get("player"), e["tick"])
                for e in game["events"]
                if e["kind"] == "board_step"
            ]
        )
    assert timing[0] and timing[1] and timing[0] != timing[1]
    assert sum(tick for _, tick in timing[1][:5]) <= sum(
        tick for _, tick in timing[0][:5]
    )


def test_migrate_active_auto_manual_and_resume_after_pause(office):
    s, pack = office
    advance(s)
    state = s.read()
    c = state["career"]
    assert c["training"]["nextDay"] == c["date"]
    old_history = deepcopy(c["history"])
    del c["training"]
    with s.transaction():
        s.write(state)
        for slot in ("1", "2", "auto"):
            s.careers.save(state, slot)
    path = Path(s.db.execute("PRAGMA database_list").fetchone()[2])
    restarted = Store(path)
    try:
        for slot in ("1", "2", "auto"):
            command(restarted, "career-load", dict(slot=slot))
            after = restarted.read()["career"]
            assert after["history"] == old_history and after[
                "training"
            ] == training.new(c["date"])
            assert not after["training"]["days"]
        assert (
            restarted.db.execute("SELECT count(*) FROM checkpoint_backup").fetchone()[0]
            >= 4
        )
        command(restarted, "career-quick", {"fixture": c["queue"][0]["id"]})
        advance(restarted)
        assert restarted.read()["career"]["training"]["days"]
    finally:
        restarted.db.close()


def test_world_plans_and_competition_isolation(tmp_path):
    from backend import competition_scene

    s = Store(tmp_path / "scene.sqlite")
    pack = s.careers.pack(competition_scene.source(database.STAFF_RELEASE, 1))
    team = next(t for t, r in pack["teams"].items() if r["name"] == "Team Vitality")
    command(
        s,
        "career-create",
        dict(
            id=database.STAFF_RELEASE,
            revision=1,
            team=team,
            mode="manager",
            scope="full",
            name="QA",
        ),
    )
    c = s.read()["career"]
    sid = next(iter(staff.team_people(c, pack, team)))
    command(s, "career-staff", dict(person=sid, duty="practice"))
    c = s.read()["career"]
    # Clubs already registered for an opening round have scheduling priority.
    day = training.offset(c["date"], 35)
    c["date"] = day
    training.refresh_practices(c, pack)
    future = [e for e in c["queue"] if e.get("delegated") and e["date"] >= day]
    assert future and all(not training.unavailable(c, e) for e in future)
    event = future[0]
    official = deepcopy(c["circuit"])
    history = list(c["history"])
    c["queue"] = [event]
    result = career.simulate(career.initial(pack, c, event, detailed=False))
    s.careers.record(c, result)
    assert c["history"] == history and c["circuit"] == official
    assert s.careers.report(c["training"]["practice"][0]["result"]) == result
    day = event["date"]
    before = c["training"]["fixturesPlayed"]
    training.run_day(c, pack, day)
    assert c["training"]["fixturesPlayed"] > before
    assert set(c["training"]["players"]) == {
        pid for tid in c["teams"] for pid in training.members(c, pack, tid)
    }
    assert c["circuit"] == official and c["history"] == history
    s.db.close()
