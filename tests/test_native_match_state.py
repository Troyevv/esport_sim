from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("backend._match_native")
from tests.reference_kernel import cs2_maps, match, match_ai
from backend import native_match_state

FIXTURES = Path(__file__).parent / "fixtures/r54"


def read_checkpoint(name="de_nuke"):
    return json.loads(gzip.decompress((FIXTURES / (name + ".checkpoint.json.gz")).read_bytes()))


def restore(world):
    return native_match_state.restore(json.dumps(world, ensure_ascii=False))


def assert_same(owner, reference):
    # Preserve insertion order for subsequent events and distinguish JSON numbers from booleans.
    assert json.dumps(json.loads(owner.snapshot()), ensure_ascii=False) == json.dumps(reference, ensure_ascii=False)


def test_full_snapshot_roundtrip_and_version_guard():
    for file in FIXTURES.glob("*.gz"):
        data = gzip.decompress(file.read_bytes())
        assert_same(native_match_state.restore(data), json.loads(data))
    for key, value in (("checkpointVersion", 99), ("rules", "future"), ("map_version", 0)):
        world = read_checkpoint()
        world[key] = value
        with pytest.raises(ValueError):
            restore(world)


def test_commands_clock_rules_upgrade_and_independent_owners():
    expected = read_checkpoint()
    expected.update(phase="freeze", deadline=expected["tick"] + 40, remaining=3, pending=False,
                    rules=cs2_maps.PREVIOUS_RULES, nextBoard={"id": "plan"})
    expected["agents"].reverse()
    expected["agents"][0]["evidence"] = {"last": "Контакт"}
    owner = restore(expected)
    for kind, value in (("timeout", None), ("call", "Выход B"), ("resume", None)):
        match.command(expected, kind, value)
        owner.command(kind, value or "")
        assert_same(owner, expected)
    before = owner.snapshot()
    with pytest.raises(ValueError):
        owner.command("call", "Выход A")
    assert before == owner.snapshot()
    fork = native_match_state.restore(before)
    for _ in range(44):
        match.advance(expected)
    assert owner.advance_intermission(500) == 44
    assert owner.advance_intermission(500) == 0
    assert_same(owner, expected)
    assert fork.snapshot() == before


def test_radio_delivery_order_scope_and_rollback():
    w = read_checkpoint()
    w["phase"] = "live"
    guards = [a for a in w["agents"] if a["team"] == "CT"]
    captain = next(a for a in guards if a["id"] == w["plans"]["CT"]["captain"])
    sender = next(a for a in guards if a is not captain)
    w["plans"]["CT"]["review"] = w["tick"] + 100
    w["messages"] = []
    now = w["tick"]
    def send(due=now, **payload):
        w["messages"].append(dict(team="CT", sender=sender["id"], due=due, **payload))
    pos = [captain[k] for k in ("x","y","z")]
    send(due=now+10, site="B")
    send(crossing=dict(tick=now, feedback=True))
    send(crossing=dict(tick=now-1, feedback=True))
    send(pressure=dict(tick=now, origin=pos, bearing=[0,0,0,1]))
    send(friendlyUtility=dict(end=now+8,kind="Дым"))
    send(blockedSite="A")
    send(site="A")
    send(device=dict(x=2,y=3,z=4,site="B",carrier=None))
    send(sight=dict(id="T1", source="Зрение", tick=now, carryingC4=True, groupSize=2))
    send(sight=dict(id="T1", source="Граната", tick=now-1))
    send(sight=dict(id="Шум", source="Слух", tick=now))
    send(due=now+4, site="A")
    owner = restore(w)
    match_ai.deliver_radio(w, [p for p in w["agents"] if p["hp"]], True)
    owner.deliver_radio()
    assert_same(owner, w)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: owner.deliver_radio(), range(12)))
    assert_same(owner, w)
    send(site="A")
    send(sight={"source": "Слух"})
    invalid = restore(w)
    before = invalid.snapshot()
    with pytest.raises((RuntimeError, IndexError, KeyError)):
        invalid.deliver_radio()
    assert invalid.snapshot() == before


@pytest.mark.parametrize(("side","reason"), [("CT","Время"),("T","Взрыв C4"),("CT","Обезвреживание"),("T","Устранение")])
def test_round_settlement_preserves_stats_accounts_and_event_order(side, reason):
    w = read_checkpoint()
    w["round"] = 30
    a, b = w["agents"][0], w["agents"][5]
    w["kills"] = [dict(target=b["id"], player=a["id"], enemy=True, weapon="AK-47",
                       assists=[w["agents"][1]["id"]], trade=w["agents"][2]["id"])]
    b["hp"] = 0
    a["cash"] = 15999
    if reason != "Время":
        w["bomb"]["site"] = "B"
    w["clutch"][side] = next(p["id"] for p in w["agents"] if p["team"] == side)
    w["plans"]["CT"]["board"] = dict(id="state",revision=7,name="Контроль",side="CT",buy="Полная")
    for p in w["agents"]:
        w["scoreByTeam"][p["teamId"]] = 15
    w["score"] = [15,15]
    owner = restore(w)
    match.finish_round(w,side,reason)
    owner.finish_round(side,reason)
    assert_same(owner,w)
    owner.finish_round(side,reason)
    assert_same(owner,w)


@pytest.fixture(scope="module")
def nuke_spawns(tmp_path_factory):
    from zipfile import ZipFile
    folder = tmp_path_factory.mktemp("r54arena") / "de_nuke"
    folder.mkdir()
    pack = Path(__file__).parents[1] / "resources/cs2/26879581/de_nuke.zip"
    with ZipFile(pack) as bundle:
        for member in ("provenance.json", "gameplay.json"):
            (folder / member).write_bytes(bundle.read(member))
    return cs2_maps.Map(folder)


@pytest.mark.parametrize(("round_number","pending"),[(1,False),(12,True),(24,False),(27,False),(30,False)])
def test_result_deadline_resets_and_archives_native_round(nuke_spawns,monkeypatch,round_number,pending):
    w = read_checkpoint()
    w.update(round=round_number,phase="result",pending=pending,deadline=w["tick"]+3,remaining=1)
    w["agents"][0].update(holster={"weapon":"AK-47","ammo":2,"reserve":1})
    w["agents"][1].update(hp=0)
    monkeypatch.setattr(cs2_maps, "for_match", lambda _: nuke_spawns)
    owner = native_match_state.restore(json.dumps(w),nuke_spawns)
    for _ in range(3):
        match.advance(w)
    assert owner.advance_intermission(3) == 3
    assert_same(owner,w)


@pytest.fixture(scope="module")
def combat_arenas(nuke_spawns):
    from zipfile import ZipFile
    from backend.native_physics import NativePerceptionMap

    folder = nuke_spawns.folder
    with ZipFile(Path(__file__).parents[1] / "resources/cs2/26879581/de_nuke.zip") as pack:
        for member in ("collision.json", "collision.bin"):
            (folder / member).write_bytes(pack.read(member))
    return nuke_spawns, NativePerceptionMap(folder)


def test_combat_resolves_damage_assists_drops_rng_and_rollback(combat_arenas):
    old, new = combat_arenas
    w = read_checkpoint()
    shooter, target = w["agents"][0], w["agents"][5]
    ids = {a["id"]: a for a in w["agents"]}
    for a in w["agents"]:
        a.update(hp=0, visible=[])
    shooter.update(hp=100, weapon="Nova", ammo=5,rng=52)
    target.update(hp=1, armor=1, helmet=True,
                  attackers={w["agents"][1]["id"]:42}, x=shooter["x"] + 1, y=shooter["y"], z=shooter["z"])
    w["bomb"]["carrier"] = target["id"]
    sight = {k:target[k] for k in ("id","x","y","z")}
    owner = native_match_state.restore(encode_world(w),physics=new)
    action = dict(actor=shooter["id"],kind="shoot",target=sight)
    before = owner.snapshot()
    with pytest.raises(ValueError):
        owner.resolve_actions(encode_world([action, dict(actor="missing",kind="shoot",target=sight)]))
    assert owner.snapshot() == before
    match.resolve_attacks(w,[(shooter,"shoot",sight)], [shooter,target],ids,old)
    owner.resolve_actions(encode_world([action]))
    assert w["kills"] and not target["hp"]
    assert w["kills"][-1]["assists"] == [w["agents"][1]["id"]]
    assert_same(owner,w)


def encode_world(v):
    return json.dumps(v, ensure_ascii=False)


@pytest.mark.parametrize("kind",["Дым","Свет","HE","Огонь","Ложная"])
def test_throw_and_effects_on_landing(combat_arenas,kind):
    old,new = combat_arenas
    w = read_checkpoint()
    actor = w["agents"][0]
    actor["utility"] = [kind]
    target = {k: actor[k] for k in ("x","y","z")} | {"utility":kind,"purpose":"Сценарий"}
    ids = {a["id"]: a for a in w["agents"]}
    w["effects"], w["recentEffects"] = [], []
    owner = native_match_state.restore(encode_world(w),physics=new)
    match_ai.throw(w,actor,target,old)
    owner.resolve_actions(encode_world([dict(actor=actor["id"],kind="throw",target=target)]))
    assert_same(owner,w)
    w["tick"] = w["effects"][0]["land"]
    owner = native_match_state.restore(encode_world(w),physics=new)
    match_ai.apply_effects(w,ids,old)
    owner.apply_effects()
    assert_same(owner,w)


def test_site_volumes_include_exact_faces_edges_and_legal_nav_points(combat_arenas):
    old, new = combat_arenas
    points = [p for site in old.plant_surfaces.values() for p in site]
    for solids in old.sites.volumes.values():
        for solid in solids:
            for face in solid.faces:
                for x, y, z in face:
                    points.append(old.to_sim((x,y,z-1)))
    for p in points + [old.centers[i] for i in list(old.centers)[::23]]:
        assert new.objectives.site_at(p) == old.site_at(p)


@pytest.mark.parametrize("mode",["plant","planted","defuse","explode","time","interrupt"])
def test_full_intent_resolution_on_objective_and_timer_boundaries(combat_arenas,mode,monkeypatch):
    old,new = combat_arenas
    monkeypatch.setattr(cs2_maps, "for_match", lambda _: old)
    w=read_checkpoint()
    t=next(a for a in w["agents"] if a["team"]=="T")
    ct=next(a for a in w["agents"] if a["team"]=="CT")
    goal=old.site_points["A"]
    t.update(x=goal[0],y=goal[1],z=goal[2])
    ct.update(x=goal[0],y=goal[1],z=goal[2])
    w["action"]=None
    w["phase"]="planted" if mode in ("defuse","explode") else "live"
    w["deadline"]=w["tick"] if mode in ("time","explode") else w["tick"]+300
    w["bomb"]=dict(carrier=t["id"],site=None,x=goal[0],y=goal[1],z=goal[2])
    if w["phase"]=="planted":
        w["bomb"].update(site="A",carrier=None)
    if mode in ("planted","interrupt","explode","defuse"):
        defusing = mode in ("explode","defuse")
        w["action"]=dict(kind="defuse" if defusing else "plant",player=(ct if defusing else t)["id"],
                         site=None if defusing else "A",start=w["tick"]-100,end=w["tick"])
    actor = ct if w["phase"]=="planted" else t
    kind = {"plant":"plant","planted":"objective","defuse":"objective","explode":"objective"}.get(mode,"hold")
    intents=[(actor,kind,"A" if kind=="plant" else None)]
    owner = native_match_state.restore(encode_world(w),physics=new)
    owner.resolve_intents(encode_world([dict(actor=a["id"],kind=k,target=p) for a,k,p in intents]))
    ids={a["id"]:a for a in w["agents"]}
    match.resolve_intents(w,intents,[a for a in w["agents"] if a["hp"]],ids,old)
    assert_same(owner,w)


def test_contact_memory_expiry_reacquisition_and_reports(combat_arenas):
    old,new=combat_arenas
    w=read_checkpoint()
    w["phase"]="planted"
    w["messages"]=[]
    w["effects"]=[]
    for a in w["agents"]:
        a.update(hp=0,knowledge={},visible=[])
    observer, opponent=w["agents"][5],w["agents"][0]
    x,y,z=old.site_points["A"]
    observer.update(hp=100,x=x,y=y,z=z,heading=0.,blind=0)
    opponent.update(hp=100,x=x+.5,y=y,z=z,heading=0.,blind=1000)
    w["bomb"]["carrier"]=opponent["id"]
    observer["knowledge"]["Шум"]=dict(id="Шум",tick=w["tick"]-75,source="Слух")
    for age, offset, blind in [(0,.5,0),(1,1.,0),(2,2.,0),(3,2.,1000),(5,2.,0)]:
        w["tick"]=150+age
        opponent["x"]=x+offset
        observer["blind"]=blind
        owner=native_match_state.restore(encode_world(w),physics=new)
        owner.observe()
        match_ai.observe(w,[a for a in w["agents"] if a["hp"]],old)
        assert_same(owner,w)
    assert "Шум" not in observer["knowledge"]
    assert observer["knowledge"][opponent["id"]]["carryingC4"]


@pytest.mark.parametrize("side",["T","CT"])
@pytest.mark.parametrize("scenario",[None,"Пистолетная","Эко","Частичная","Форс","Полная","Антиэко","Бонусная"])
def test_budget_equipment_donations_and_purchase_ledger(side,scenario):
    from tests.reference_kernel import cs2_economy
    w=read_checkpoint()
    w.update(phase="freeze",round=8)
    squad=[p for p in w["agents"] if p["team"]==side]
    for p,cash in zip(squad,[15900,300,3200,4700,1600],strict=True):
        p.update(cash=cash,weapon="Glock",ammo=2,reserve=0,holster=None,armor=0,helmet=False,utility=[])
    squad[-1]["holster"]=dict(weapon="Nova",ammo=1,reserve=4)
    board={"format":1,"slots":[[dict(kind="throw",utility="Дым"),dict(kind="throw",utility="Дым")]
                              if i==1 else [] for i in range(5)]}
    owner=restore(w)
    strategy=cs2_economy.decision(w,squad,site="B",profile=cs2_maps.PROFILES[w["mapId"]],board=board,requested=scenario)
    actual=json.loads(owner.buy_decision(side,encode_world(dict(site="B",board=board,requested=scenario))))
    assert encode_world(strategy)==encode_world(actual)
    owner.buy_equipment(side,encode_world(actual),encode_world(board))
    cs2_economy.buy(w,squad,strategy,match.purchase,board)
    assert_same(owner,w)


def test_board_assignment_before_start_and_during_timeout(combat_arenas, monkeypatch):
    from backend import tactics

    space, _ = combat_arenas
    monkeypatch.setattr(cs2_maps, "get", lambda name: space)
    monkeypatch.setattr(tactics.cs2_maps, "get", lambda name: combat_arenas[1])
    w = read_checkpoint()
    w.update(tick=0, round=1, phase="freeze", started=False, remaining=match.RULES["timeouts"])
    side = next(a["team"] for a in w["agents"] if a["teamId"] == w["coachTeamId"])
    pos = space.spawn(side, 0)[0]
    board = dict(format=2, id="practice", revision=3, name="Начало раунда", side=side, buy="Пистолетная",
                 map=space.name, geometry=cs2_maps.BUILD,
                 slots=[[tactics.step("face", pos, seconds=1)], [], [], [], []])
    owner = restore(w)
    match.assign(w, board)
    native_match_state.assign(owner, board)
    assert_same(owner, w)
    match.command(w, "timeout")
    owner.command("timeout")
    match.assign(w, board)
    native_match_state.assign(owner, board)
    assert_same(owner, w)
    for edits in (dict(buy="Эко"), dict(side="T" if side == "CT" else "CT")):
        with pytest.raises(ValueError):
            native_match_state.assign(owner, board | edits)
        assert_same(owner, w)


@pytest.mark.parametrize("kind", ["move", "exit", "retreat", "wait", "hold", "face", "plant",
                                  "throw", "throw-cooldown", "throw-missing", "wait-finished", "ready"])
def test_native_editor_step_matches_agent_decision(combat_arenas, kind):
    from backend import tactics

    arena, physics = combat_arenas
    w = read_checkpoint()
    squad = [a for a in w["agents"] if a["team"] == "T"]
    a = squad[0]
    site = arena.site_points["A"]
    spawn, _, area = arena.spawn("T", 0)
    pos = site if kind == "plant" else spawn
    a.update(x=pos[0], y=pos[1], z=pos[2], navArea=arena.locate(pos), path=[], dest=[], blockedTicks=0,
             stepIndex=0, stepReady=0, stepUntil=None, target=None, visible=[], knowledge={}, throwAt=0,
             utility=["Дым"], ammo=4, reserve=0, reloadAt=0)
    w.update(phase="live", action=None, deadline=w["tick"]+10)
    w["bomb"].update(carrier=a["id"], site=None)
    name = kind.split("-")[0] if kind != "ready" else "move"
    goal = arena.centers[area] if name in ("move", "exit", "retreat") else pos
    step = tactics.step(name, goal)
    if name in ("wait", "hold", "face"):
        step["seconds"] = 2
    if name == "throw":
        step["utility"] = "Дым"
    if kind == "throw-cooldown":
        a["throwAt"] = w["tick"] + 1
    if kind == "throw-missing":
        a["utility"] = []
    if kind == "wait-finished":
        a["stepUntil"] = w["tick"]
    if kind == "ready":
        a["stepReady"] = w["tick"] + 2
    plan = w["plans"]["T"]
    plan.update(rotated=False, board=dict(id="round-opener", revision=2, map=arena.name,
                                         slots=[[step] if i == a["slot"] else [] for i in range(5)]))
    player = w["domain"]["players"][a["playerId"]]
    owner = native_match_state.restore(encode_world(w), physics=physics)
    observation = dict(space=arena, player=player, tick=w["tick"], plan=plan, phase="live",
                       chemistry=w["domain"]["chemistry"], action=None, deadline=w["deadline"])
    intent = match_ai.act(observation, a, squad, w["bomb"], [])
    assert json.loads(owner.board_step(a["id"], encode_world(w["bomb"]), [])) == list(intent)
    assert_same(owner, w)


@pytest.mark.parametrize(("budget", "style", "coach"), [
    ("Пистолетная", "Сбор", None), ("Антиэко", "Быстро", None), ("Частичная", "Быстро", None),
    ("Полная", "Быстро", "Выход B"), ("Эко", "Сбор", "Экономить"),
])
def test_captain_openings_consume_only_captain_rng(combat_arenas, budget, style, coach):
    from tests.reference_kernel import cs2_openings, cs2_play

    arena, physics = combat_arenas
    w = read_checkpoint()
    for side in ("T", "CT"):
        squad = [a for a in w["agents"] if a["team"] == side]
        captain = next(a for a in squad if a["appointed"])
        w.setdefault("siteHistory", {})[captain["teamId"]] = [["A", False], ["B", True]]
        w.setdefault("defensiveHistory", {})[captain["teamId"]] = ["A", None, "A"]
        owner = native_match_state.restore(encode_world(w), physics=physics)
        expected = cs2_play.opening(arena, w, squad, captain, w["domain"]["players"][captain["playerId"]],
                                    budget, "A", style, coach)
        actual = owner.opening_call(side, budget, "A", style, encode_world(coach))
        assert json.loads(actual) == list(expected)
        assert_same(owner, w)
        if side == "CT":
            assert json.loads(owner.defensive_read()) == cs2_play.defensive_read(w, captain)
            plan = dict(site="A", buy=budget)
            result = cs2_openings.select(arena, plan, squad, w["domain"]["players"], captain, "B", None)
            assert json.loads(owner.select_defense(encode_world(plan), '"B"', "null")) == json.loads(encode_world(result))
            assert_same(owner, w)
        else:
            plan = w["plans"]["T"]
            expected = cs2_play.default_probe(arena, squad, w["bomb"]["carrier"], plan, w["tick"], w["domain"])
            assert json.loads(owner.default_probe(encode_world(plan))) == expected


@pytest.mark.parametrize(("site", "lane"), [("A", 0), ("B", 1)])
def test_both_sides_have_identical_role_orders_from_restored_positions(combat_arenas, site, lane):
    arena, physics = combat_arenas
    w = read_checkpoint()
    owner = native_match_state.restore(encode_world(w), physics=physics)
    for side in ("T", "CT"):
        squad = [a for a in w["agents"] if a["team"] == side]
        expected = arena.orders(side, site, squad, lane, "Сбор")
        actual = owner.attack_orders(site, lane, "Сбор") if side == "T" else owner.defense_orders(site, lane)
        assert json.loads(actual) == expected
        assert_same(owner, w)


@pytest.mark.parametrize("coach_call", [None, "Ускориться", "Экономить", "Выход A", "board"])
def test_native_freeze_opens_full_round_with_roles_economy_and_calls(combat_arenas, monkeypatch, coach_call):
    arena, physics = combat_arenas
    monkeypatch.setattr(cs2_maps, "for_match", lambda _: arena)
    w = read_checkpoint()
    match.next_round(w)
    if coach_call == "board":
        side = next(a["team"] for a in w["agents"] if a["teamId"] == w["coachTeamId"])
        w["nextBoard"] = dict(id="saved", revision=2, name="Пауза", side=side, map=arena.name, geometry=cs2_maps.BUILD,
                              format=2, buy="Эко", slots=[[], [], [], [], []])
    else:
        w["call"] = coach_call
    owner = native_match_state.restore(encode_world(w), arena, physics=physics)
    ticks = w["deadline"] - w["tick"]
    for _ in range(ticks):
        match.advance(w)
    assert owner.advance_intermission(ticks) == ticks
    assert w["phase"] == "live"
    assert_same(owner, w)


@pytest.mark.parametrize("scenario", ["blocked", "leader-lost", "carrier", "retake", "radio-gap"])
def test_captain_reviews_update_only_from_team_observations(combat_arenas, scenario):
    arena, physics = combat_arenas
    w = read_checkpoint()
    side = "T" if scenario in ("blocked", "leader-lost") else "CT"
    squad = [a for a in w["agents"] if a["team"] == side and a["hp"]]
    leader = next(a for a in squad if a["appointed"])
    plan = w["plans"][side]
    plan.update(review=0, start=0)
    if scenario == "blocked":
        leader["routeReports"] = {leader["id"]: [plan["site"], w["tick"]]}
    if scenario == "leader-lost":
        leader["hp"] = 0
        squad.remove(leader)
    if scenario == "carrier":
        opponent = next(a for a in w["agents"] if a["team"] != side)
        leader["knowledge"][opponent["id"]] = dict(id=opponent["id"], **dict(zip(("x", "y", "z"), arena.site_points["B"])),
                                                    tick=w["tick"], source="Радио", carryingC4=True,
                                                    weapon="AK-47", groupSize=3)
    if scenario == "retake":
        w.update(phase="planted", deadline=w["tick"] + 350)
        leader["heardSite"] = "A"
    if scenario == "radio-gap":
        plan["backup"] = dict(id=squad[-1]["id"], site="B", lane=1, hold=list(arena.site_points["B"]),
                              watch=list(arena.site_points["A"]), lastEvidence=w["tick"] - 7)
    owner = native_match_state.restore(encode_world(w), physics=physics)
    owner.review_captain(side)
    match_ai.captain(w, squad, arena)
    assert_same(owner, w)


@pytest.mark.parametrize("scenario", ["sight", "aim", "reload", "empty", "last-burst", "use", "save", "fire"])
def test_contact_and_survival_decisions_from_limited_view(combat_arenas, scenario):
    arena, physics = combat_arenas
    w = read_checkpoint()
    a, target = w["agents"][0], w["agents"][5]
    squad = [p for p in w["agents"] if p["team"] == a["team"] and p["hp"]]
    w.update(phase="live", action=None)
    sight = {k: target[k] for k in ("id", "x", "y", "z", "weapon")}
    sight.update(source="Зрение", tick=w["tick"], speed=.5, bodySector=2, interaction=None)
    a.update(knowledge={target["id"]:sight}, visible=[target["id"]], target=target["id"], ready=0, utility=[],
             hp=100, ammo=15, reserve=30, reloadAt=0, shelter=None, coverReview=w["tick"]+50)
    if scenario == "aim":
        a["target"] = None
    if scenario in ("reload", "empty"):
        a.update(ammo=0, reserve=0 if scenario == "empty" else 30)
    if scenario == "last-burst":
        a.update(visible=[], ammo=30)
        sight.update(tick=w["tick"]-1)
        for mate in squad:
            if mate is not a:
                mate["hp"] = 0
        squad = [a]
    if scenario == "use":
        w["action"] = dict(kind="plant", player=a["id"], end=w["tick"]+1)
    if scenario == "save":
        w["phase"] = "planted"
        a["saving"] = list(arena.site_points["B"])
    fire = [dict(x=a["x"] + 2, y=a["y"], z=a["z"], radius=4)] if scenario == "fire" else []
    player = w["domain"]["players"][a["playerId"]]
    owner = native_match_state.restore(encode_world(w), physics=physics)
    context = dict(space=arena, player=player, tick=w["tick"], plan=w["plans"][a["team"]], phase=w["phase"],
                   chemistry=w["domain"]["chemistry"], action=w["action"], deadline=w["deadline"])
    actual = json.loads(owner.priority_intent(a["id"], encode_world(dict(action=w["action"], device=w["bomb"], fire=fire))))
    expected = match_ai.act(context, a, squad, w["bomb"], fire)
    assert actual == list(expected)
    assert_same(owner,w)


def test_autonomous_ticks_observer_frames_and_restoration(combat_arenas, monkeypatch):
    from backend import engine
    old, physics = combat_arenas
    monkeypatch.setattr(cs2_maps, "for_match", lambda w: old)
    reference = read_checkpoint()
    owner = native_match_state.restore(encode_world(reference), old, physics=physics)
    for size in (45, 180, 202):
        assert owner.advance(size) == size
        for _ in range(size):
            match.advance(reference)
        assert_same(owner, reference)
        owner = native_match_state.restore(owner.snapshot(), old, physics=physics)
    expected = []
    for _ in range(8):
        expected.append(engine.motion_sample(reference))
        match.advance(reference)
    assert json.loads(owner.advance_motion(8)) == json.loads(encode_world(expected))
    assert_same(owner, reference)


def test_native_tick_batch_stops_at_timeout_without_spending_clock(combat_arenas, monkeypatch):
    old, physics = combat_arenas
    monkeypatch.setattr(cs2_maps, "for_match", lambda w: old)
    w = read_checkpoint()
    match.finish_round(w, "T", "Устранение")
    w["pending"] = True
    owner = native_match_state.restore(encode_world(w), old, physics=physics)
    remaining = w["deadline"] - w["tick"]
    assert owner.advance(remaining + 10) == remaining
    for _ in range(remaining):
        match.advance(w)
    assert_same(owner, w)
    assert owner.advance(8) == 0
    before = owner.snapshot()
    with pytest.raises(ValueError):
        owner.advance(-1)
    assert owner.snapshot() == before


def test_batch_starts_new_map_with_older_rules_and_records_exact_profile(combat_arenas, monkeypatch):
    old, physics = combat_arenas
    monkeypatch.setattr(cs2_maps, "get", lambda _: old)
    w = match.initial(41000, map_id="de_nuke")
    from backend import match as production_match, cs2_maps as installed_maps
    monkeypatch.setattr(installed_maps,"get",lambda _:old)
    fresh = production_match.initial(41000, map_id="de_nuke")
    assert fresh.pop("agentPolicy") == 6
    assert encode_world(fresh) == encode_world(w)
    w["rules"] = cs2_maps.PREVIOUS_RULES
    owner = native_match_state.restore(encode_world(w), old, physics=physics)
    for call in ("timeout", "resume"):
        match.command(w, call)
        owner.command(call, "")
    poses = []
    for _ in range(75):
        match.advance(w)
        if w["tick"] % 10 == 0:
            poses.append([[a[k] for k in ("id", "x", "y", "z", "hp", "navArea")] for a in w["agents"]])
    profile = json.loads(owner.profile_ticks(75))
    assert profile["samples"] == poses
    assert len(profile["durations"]) == 75
    assert_same(owner, w)


def test_depo_owner_restores_mid_board_and_continues_exact_events():
    from backend import match as production, tactics

    game = match.initial(42)
    fresh = production.initial(42)
    assert fresh.pop("agentPolicy") == 6
    assert encode_world(fresh) == encode_world(game)
    board = dict(tactics.propose("T", "Пистолетная", 17), id="depo-regression", revision=1)
    owner = native_match_state.open_game(game)
    match.assign(game, board)
    native_match_state.assign(owner, board)
    for count in (46, 80, 240):
        for _ in range(count):
            match.advance(game)
        assert owner.advance(count) == count
        assert_same(owner, game)
        owner = native_match_state.restore(owner.snapshot())


def test_failed_batch_restores_completed_round_and_archive_cursor():
    game = match.initial(27)
    game.update(phase="result", deadline=1)
    # A bad opening input fails after the old journal has moved into archive.
    game["playbook"] = {"T/Эко": {"slots": []}, "T/Оружейная": {"slots": []}}
    game["domain"]["players"][game["agents"][0]["playerId"]]["skills"].pop("aggression")
    owner = native_match_state.open_game(game)
    before = owner.snapshot()
    with pytest.raises((KeyError, IndexError, RuntimeError, ValueError)):
        owner.advance(60)
    assert owner.snapshot() == before
    assert owner.advance(1) == 1
    assert json.loads(owner.snapshot())["archive"][-1] == game["events"]


def test_depo_preserves_binary64_speed_in_visual_memory():
    game = match.initial(197)
    game["tick"] = 10
    for a in game["agents"]:
        a["hp"] = 0
    watcher, target = game["agents"][0], game["agents"][5]
    for actor in (watcher, target):
        actor.update(hp=100, x=45, y=105)
    sight = dict(id=target["id"], x=45.1, y=105.237, tick=9, source="Зрение")
    watcher["knowledge"][target["id"]] = sight
    watcher["visible"] = [target["id"]]
    owner = native_match_state.open_game(game)
    match_ai.observe(game, [watcher, target])
    owner.observe()
    assert watcher["knowledge"][target["id"]]["speed"] == 0.25723335709040107
    assert_same(owner, game)


@pytest.mark.parametrize("source_index,listener_index", [(0, 5), (5, 0)])
def test_individual_policy_gives_both_sides_an_uncertain_acoustic_report(combat_arenas, source_index, listener_index):
    _, physics = combat_arenas
    w = read_checkpoint()
    w.update(agentPolicy=1, messages=[])
    source, listener = w["agents"][source_index], w["agents"][listener_index]
    for a in w["agents"]:
        a.update(hp=0, knowledge={}, visible=[])
    source.update(hp=100, ammo=8)
    listener.update(hp=100, x=source["x"]-8, y=source["y"], z=source["z"])
    target = dict(x=source["x"]+8, y=source["y"], z=source["z"])
    owner = native_match_state.restore(encode_world(w), physics=physics)
    owner.resolve_actions(encode_world([dict(actor=source["id"], kind="shoot", target=target)]))
    after = json.loads(owner.snapshot())
    report = after["agents"][listener_index]["knowledge"]["Шум · Выстрел"]
    assert report["source"] == "Слух" and report["witness"] == listener["id"]
    assert report["id"] != source["id"] and report["x"] != source["x"]
    assert 0 < report["confidence"] < 1
    assert any(m["team"] == listener["team"] and m["sight"] == report and m["due"] > w["tick"]
               for m in after["messages"] if "sight" in m)


@pytest.mark.parametrize("index", [1, 6])
def test_peer_utility_call_reaches_only_allies_after_cast_and_delay(combat_arenas, index):
    _, physics = combat_arenas
    w = read_checkpoint()
    w.update(agentPolicy=3, messages=[])
    caster = w["agents"][index]
    caster.update(utility=["Дым"], hp=100)
    aim = dict(x=caster["x"]+12, y=caster["y"], z=caster["z"], utility="Дым")
    owner = native_match_state.restore(encode_world(w), physics=physics)
    owner.resolve_actions(encode_world([dict(actor=caster["id"], kind="throw", target=aim)]))
    w = json.loads(owner.snapshot())
    packet, = [m for m in w["messages"] if "friendlyUtility" in m]
    cast = packet["friendlyUtility"]["cast"]
    assert packet["due"] > w["tick"] and cast["point"] == [aim[k] for k in ("x", "y", "z")]
    assert all(cast not in a.get("crossingCalls", []) for a in w["agents"])
    w["tick"] = packet["due"]
    owner = native_match_state.restore(encode_world(w), physics=physics)
    owner.deliver_radio()
    after = json.loads(owner.snapshot())
    for a in after["agents"]:
        assert (cast in a.get("crossingCalls", [])) == (
            a["hp"] > 0 and a["team"] == caster["team"] and a["id"] != caster["id"]
        )
