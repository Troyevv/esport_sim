from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("backend._match_native")
from backend import cs2_maps, match, match_ai, native_match_state

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
