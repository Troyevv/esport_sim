"""Detailed match inputs, save migrations and viewer projections."""
from copy import deepcopy
import json

from . import cs2_maps, checkpoints, engine, match_inventory, match_score, tactics, world
from . import match_view, coaching
from .match_rules import AGENT_POLICY, UTILITY_STATS, CALLS, MAP, RULES, VERSION, PREVIOUS_VERSION, equipment_value


def team(w, club):
    data = w["domain"]
    return data["teams"][data["rosters"][w["rosterIds"][club]]["team"]]

def check_coach(w):
    world.authorize(
        w["domain"]["authority"],
        w["domain"]["teams"][w["coachTeamId"]]["organization"],
        "coach_match",
    )

def bind_rosters(w, data, roster_ids, coach_id=None):
    world.validate(data)
    if len(roster_ids) != 2 or roster_ids[0] == roster_ids[1]:
        raise ValueError("Нужны два разных состава")
    w.update(
        domain=data,
        rosterIds=list(roster_ids),
        coachTeamId=coach_id or data["rosters"][roster_ids[0]]["team"],
    )
    by_slot = {(a["club"], a["slot"]): a for a in w["agents"]}
    for club, roster in enumerate(roster_ids):
        for slot, member in enumerate(world.validate_five(data, roster)):
            a = by_slot[club, slot]
            ident = member["player"]
            label = "Капитан" if member["captain"] else world.ROLE_NAMES[member["role"]]
            a.update(
                role=label,
                playerId=ident,
                teamId=data["rosters"][roster]["team"],
                playingRole=member["role"],
                appointed=member["captain"],
                name=data["players"][ident]["name"],
            )
    check_coach(w)

def init_performance(a, now):
    a.update(
        lastMove=-100,
        lastHurt=-100,
        previousTarget=None,
        observedSpeed=0,
        movingTicks=0,
        liveStart=now,
        dayRoll=0,
        pressure=0,
        stepReady=0,
        tradeTarget=None,
        tradeUntil=0,
    )

def initial(seed, domain=None, roster_ids=world.FIXTURE_ROSTERS, coach_id=None, *, map_id="depo", first_attack=None, agent_policy=AGENT_POLICY):
    space = None if map_id=="depo" else cs2_maps.get(map_id)
    agents = [engine.spawn_slot(seed, side, slot, side_index*5+slot)
              for side_index,side in enumerate(("T","CT")) for slot in range(5)]
    w = dict(seed=seed,tick=0,agents=agents)
    w.update(
        version=2,
        checkpointVersion=checkpoints.VERSION,
        map_version=MAP["version"],
        rules=VERSION,
        round=0,
        serial=0,
        score=[0, 0],
        history=[],
        archive=[],
        events=[],
        stats={},
        streak=[0, 0],
        remaining=RULES["timeouts"],
        pending=False,
        call=None,
        feedback=[],
    )
    if agent_policy is not None:
        w["agentPolicy"] = agent_policy
    if space:
        w.update(mapId=space.name,map_version=cs2_maps.BUILD,rules=cs2_maps.RULES,checkpointVersion=7)
    # Slot identity survives side switches and loading a saved round.
    for a in w["agents"]:
        slot = int(a["id"][len(a["team"]) :]) - 1
        a.update(
            club=0 if a["team"] == "T" else 1, slot=slot, cash=0, hp=0, evidence=None
        )
        w["stats"][a["id"]] = dict(
            k=0, d=0, a=0, hs=0, damage=0, opening=0, openingDeaths=0, kast=0, spent=0, clutches=0
        )
    bind_rosters(
        w,
        world.exhibition(w["agents"]) if domain is None else deepcopy(domain),
        roster_ids,
        coach_id,
    )
    if agent_policy and agent_policy >= 12:
        from .coaching import bench
        w.update(coaches=bench(w["domain"]), talkHistory=[], talkSeconds=0, lastBreak={},
                 rivalRemaining=RULES["timeouts"], matchImportance=w["domain"].get("matchImportance", 0))
    match_score.initialize(w)
    if first_attack is not None:
        if first_attack not in match_score.team_ids(w):
            raise ValueError("Неизвестная стартующая команда")
        w["firstAttackTeamId"] = first_attack
    from . import native_match_state
    return native_match_state.start_round(w, space)


def migrate_legacy(w):
    w["rulesTransition"] = dict(
        previous=w["rules"], tick=w["tick"], lastEvent=w["serial"]
    )
    data = world.exhibition(w["agents"], legacy=True)
    roles = [a["role"] for a in w["agents"]]
    bind_rosters(w, data, world.FIXTURE_ROSTERS)
    for a, label in zip(w["agents"], roles, strict=True):
        a["role"] = label
        init_performance(a, w["plans"].get(a["team"], {}).get("start", w["tick"]))
        a["previousTarget"] = a["target"]
        for key in ("aim", "reaction", "comms", "tactics"):
            del a[key]
    w["rules"] = VERSION

def validate_bindings(w):
    data = w["domain"]
    world.validate(data)
    if (
        len(w["rosterIds"]) != 2
        or len(set(w["rosterIds"])) != 2
        or len(w["agents"]) != 10
    ):
        raise ValueError("Некорректный состав BO1")
    match_score.validate(w)
    match_inventory.validate(w)
    by_slot = {(a["teamId"], a["slot"]): a for a in w["agents"]}
    for club, roster in enumerate(w["rosterIds"]):
        for slot, m in enumerate(world.validate_five(data, roster)):
            a = by_slot[data["rosters"][roster]["team"], slot]
            clocks = (
                "lastMove",
                "lastHurt",
                "movingTicks",
                "liveStart",
                "stepReady",
                "tradeUntil",
            )
            if any(type(a[k]) is not int for k in clocks) or not (
                0 <= a["movingTicks"] <= w["tick"]
                and -8 <= a["dayRoll"] <= 8
                and a["pressure"] in (0, 1)
                and 0 <= a["observedSpeed"] < float("inf")
            ):
                raise ValueError("Некорректное состояние исполнения игрока")
            for key in ("tradeTarget", "previousTarget"):
                if a[key] is not None and a[key] not in w["stats"]:
                    raise ValueError("Неизвестная цель игрока")
            if (
                a["club"],
                a["slot"],
                a["playerId"],
                a["playingRole"],
                a["appointed"],
            ) != (club, slot, m["player"], m["role"], m["captain"]):
                raise ValueError("Участник матча расходится с заявленной пятёркой")
    check_coach(w)

def command(w, kind, value=None):
    from . import native_match_state
    owner = native_match_state.restore(json.dumps(w))
    if kind == "address":
        from .coaching import validate_address
        validate_address(value)
        value = json.dumps(value, ensure_ascii=False)
    owner.command(kind, value or "")
    result = json.loads(owner.snapshot())
    w.clear()
    w.update(result)


def assign(w, board):
    from . import native_match_state
    w.update(native_match_state.assign_checkpoint(w, board))


def advance(w, ticks=1):
    """One-shot stepping for callers with a detached checkpoint."""
    from . import native_match_state
    owner = native_match_state.open_game(w)
    owner.advance(ticks)
    result = json.loads(owner.snapshot())
    w.clear()
    w.update(result)


def play_map(w):
    from . import native_match_state
    native_match_state.play_map(w)


def project(w, view="full"):
    from . import native_match_state
    space=cs2_maps.for_match(w)
    if view not in ("full", "T", "CT"):
        raise ValueError("Неизвестный режим обзора")
    own = [a for a in w["agents"] if a["team"] == view]
    visible = {ident for a in own if a["hp"] for ident in a["visible"]}
    agents = []
    for a in w["agents"]:
        friendly = view == "full" or a["team"] == view
        if not friendly and (a["id"] not in visible or not a["hp"]):
            continue
        marker = {
            k: a[k]
            for k in (
                "id",
                "name",
                "team",
                "x",
                "y",
                "heading",
                "weapon",
                "role",
                "club",
            )
        }
        if space:
            marker["z"]=a["z"]
        marker.update(
            alive=bool(a["hp"]),
            status=a["status"] if friendly else "В поле зрения",
            visible=a["visible"] if friendly else [],
            knowledge=list(a["knowledge"].values()) if friendly else [],
        )
        if friendly:
            primary, secondary = match_inventory.slots(a) if a["hp"] else (None, None)
            marker.update(primary=primary, secondary=secondary)
            marker.update(
                playerId=a["playerId"],
                equipmentValue=equipment_value(a) if a["hp"] else 0,
            )
            marker.update(
                {
                    k: a[k]
                    for k in (
                        "hp",
                        "armor",
                        "helmet",
                        "ammo",
                        "reserve",
                        "cash",
                        "utility",
                        "kit",
                    )
                }
            )
        if friendly and a["hp"]:
            marker["flashLevel"] = a.get("flashLevel", float(a["blind"] > w["tick"]))
        agents.append(marker)
    bomb = w["bomb"]
    carrier = next((a for a in w["agents"] if a["id"] == bomb["carrier"]), None)
    point = carrier or bomb
    smoke = [f for f in w["effects"] if f["kind"] == "Дым" and f["land"] <= w["tick"]]

    def blocks(a, p, f):
        if "lobes" not in f:
            return match_view.near_line(a, p, f, f["radius"])
        return any(c["reach"] > 0 and match_view.near_line(a, p, match_view.at(c["p"]), c["reach"])
                   for c in f["lobes"])

    def observable(p, *, exclude=None):
        return view == "full" or any(
            a["hp"]
            and a["blind"] <= w["tick"]
            and match_view.sees(space,a,p)
            and not any(
                blocks(a, p, f) for f in smoke if (f.get("player"), f.get("start")) != exclude
            )
            for a in own
        )

    public_bomb = None
    if point["x"] is not None and (
        view in ("full", "T")
        or (carrier and carrier["id"] in visible)
        or (not carrier and observable(point))
    ):
        public_bomb = dict(
            **match_view.at(match_view.point(point)), carrier=bomb["carrier"], site=bomb["site"]
        )
    effects = []
    active_effects = {(f.get("player"), f.get("start")): f for f in w["effects"]}
    for f in w["recentEffects"]:
        key = f["player"], f["start"]
        live = active_effects.get(key, {})
        own_effect = view in ("full", f["team"])
        exclude = key if f["kind"] == "Дым" else None
        if not own_effect and w["tick"] < f["land"]:
            continue
        volume = None
        if "lobes" in live:
            volume = [[*c["p"], c["reach"]] for c in live["lobes"] if c["reach"] > 0 and
                      (own_effect or observable(match_view.at(c["p"]), exclude=exclude))]
        if not own_effect and not volume and not observable(f, exclude=exclude):
            continue
        item = dict(f)
        if not own_effect:
            item.pop("trajectory", None)
            item.pop("sz", None)
            item.update(sx=f["x"], sy=f["y"], player=None)
        if w.get("agentPolicy", 0) >= 6:
            item.pop("weapon", None)
            item["spatial"] = True
            if volume is not None:
                item["volume"] = volume
        effects.append(item)
    stats = []
    for a in w["agents"]:
        row = dict(
            id=a["id"],
            name=a["name"],
            club=a["club"],
            teamId=a["teamId"],
            team=a["team"],
            role=a["role"],
            **w["stats"][a["id"]],
        )
        if view not in ("full", a["team"]) and w["phase"] != "finished":
            row["spent"] = None
        if "visual" in w["domain"]["players"][a["playerId"]]:
            row["visual"] = w["domain"]["players"][a["playerId"]]["visual"]
        if w.get("agentPolicy", 0) >= 6:
            for metric in UTILITY_STATS:
                if view == "full" or w["phase"] == "finished":
                    row.setdefault(metric, 0)
                else:
                    row.pop(metric, None)
        stats.append(row)
    audience = lambda e: view == "full" or e["team"] in (view, None)
    journal = [
        e
        for e in w["events"]
        if audience(e) and e["kind"] not in ("money", "buy", "shot", "damage")
    ]
    if view != "full":
        journal = [{k: v for k, v in e.items() if k != "owner"} if e["kind"] == "flash" else e for e in journal]
    action = w["action"]
    if action and view not in (
        "full",
        next(a["team"] for a in w["agents"] if a["id"] == action["player"]),
    ):
        action = None
    ids = match_score.team_ids(w)
    sides = {a["teamId"]: a["team"] for a in w["agents"]}
    coach_view = view in ("full", sides[w["coachTeamId"]])
    ratings = {}
    known = w["domain"].get("managerPlayers")
    coached = [a for a in w["agents"] if a["teamId"] == w["coachTeamId"]]
    coach_view = coach_view and not w.get("autonomous") and not w.get("series", {}).get("spectator")
    if coach_view:
        for a in w["agents"]:
            if a["teamId"] == w["coachTeamId"] and (known is None or a["playerId"] in known):
                ratings[a["id"]] = world.player_report(w["domain"], a["playerId"])[
                    "ratings"
                ]
    return dict(
        seed=w["seed"],
        tick=w["tick"],
        time=w["tick"] / 10,
        map=space.descriptor if space else MAP,
        agents=agents,
        view=view,
        events=journal[-48:],
        match=dict(
            rules=w["rules"],
            source=w["domain"]["source"],
            roleRatings=ratings,
            teamRating=(
                world.team_rating(
                    w["domain"],
                    next(
                        r
                        for r in w["rosterIds"]
                        if w["domain"]["rosters"][r]["team"] == w["coachTeamId"]
                    ),
                    space.name.removeprefix("de_") if space else MAP["id"],
                )
                if coach_view and (known is None or all(a["playerId"] in known for a in coached))
                else None
            ),
            round=w["round"],
            phase=w["phase"],
            clock=max(0, w.get("breakEnds",w["deadline"]) - w["tick"]),
            teams=[team(w, i)["name"] for i in (0, 1)],
            teamVisuals=[team(w, i).get("visual") for i in (0, 1)],
            score=w["score"],
            sides=[sides[tid] for tid in ids],
            clubs=[
                dict(
                    id=tid,
                    name=w["domain"]["teams"][tid]["name"],
                    side=sides[tid],
                    visual=w["domain"]["teams"][tid].get("visual"),
                    score=w["scoreByTeam"][tid],
                )
                for tid in ids
            ],
            coachTeamId=w["coachTeamId"],
            winnerTeamId=w["winnerTeamId"],
            history=[
                dict(
                    {
                        k: v
                        for k, v in h.items()
                        if k != "tactic"
                        or view in ("full", v["side"])
                        or w["phase"] == "finished"
                    },
                    economy={
                        s: v
                        for s, v in h["economy"].items()
                        if view in ("full", s) or w["phase"] == "finished"
                    },
                )
                for h in w["history"]
            ],
            stats=stats,
            bomb=public_bomb,
            resolution=(
                next(
                    (
                        dict(kind=e["kind"], tick=e["tick"])
                        for e in reversed(w["events"])
                        if e["kind"] in ("explode", "defuse")
                    ),
                    None,
                )
                if w["phase"] in ("finished", "result")
                else None
            ),
            action=action,
            effects=effects,
            shots=[
                {k: v for k, v in e.items() if k != "accuracy"}
                for e in w["traces"]
                if audience(e)
            ],
            kills=w["kills"],
            groundWeapons=[
                {k: g[k] for k in ("id", "weapon", "x", "y","z") if k in g}
                for g in w["groundWeapons"]
                if view == "full" or observable(g)
            ],
            plans={
                s: {k: v for k, v in p.items() if k != "board"}
                | ({"tactic": tactics.reference(p["board"])} if "board" in p else {})
                for s, p in w["plans"].items()
                if view in ("full", s)
            },
            prepared=(
                [tactics.reference(p) for p in w.get("playbook", {}).values()]
                if coach_view and (known is None or all(a["playerId"] in known for a in coached))
                else []
            ),
            pregame=not w.get("started")
            and w["tick"] == 0
            and w["phase"] == "freeze"
            and w["remaining"] == w.get("openingTimeouts", RULES["timeouts"]),
            nextBuy=(
                native_match_state.next_buy(w, sides[w["coachTeamId"]])
                if coach_view and (known is None or all(a["playerId"] in known for a in coached))
                else None
            ),
            room=coaching.room(w, coach_view, coached),
            breakOwner=w.get("breakOwner"),
            rivalRemaining=w.get("rivalRemaining"),
            remaining=w["remaining"],
            timeoutLimit=w.get("series",{}).get("profile",{}).get("timeouts",RULES["timeouts"]),
            pending=w["pending"],
            call=w["call"] if coach_view else None,
            calls=CALLS,
            feedback=w["feedback"] if coach_view and w["phase"] == "timeout" else [],
        ),
    )
