"""Autonomous BO1. The same step drives the home server and headless matches."""

from collections import Counter
from copy import deepcopy
from math import atan2

from . import cs2_openings, cs2_economy, cs2_maps, match_inventory
from backend import checkpoints, engine, match_score, tactics, world
from . import match_performance as perf
from backend.world import match_player as profile
from . import match_ai as ai
from .match_events import impact, emit, money
from backend.match_rules import blast_damage, equipment_value, CALLS, MAP, PRICES, RULES, VERSION, PREVIOUS_VERSION, SIDEARMS, WEAPONS, role_orders


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


def initial(seed, domain=None, roster_ids=world.FIXTURE_ROSTERS, coach_id=None, *, map_id="depo", first_attack=None):
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
    if space:
        w.update(mapId=space.name,map_version=cs2_maps.BUILD,rules=cs2_maps.RULES,checkpointVersion=7)
    # Slot identity survives side switches and loading a saved round.
    for a in w["agents"]:
        slot = int(a["id"][len(a["team"]) :]) - 1
        a.update(
            club=0 if a["team"] == "T" else 1, slot=slot, cash=0, hp=0, evidence=None
        )
        w["stats"][a["id"]] = dict(
            k=0, d=0, a=0, hs=0, damage=0, opening=0, kast=0, spent=0, clutches=0
        )
    bind_rosters(
        w,
        world.exhibition(w["agents"]) if domain is None else deepcopy(domain),
        roster_ids,
        coach_id,
    )
    match_score.initialize(w)
    if first_attack is not None:
        if first_attack not in match_score.team_ids(w):
            raise ValueError("Неизвестная стартующая команда")
        w["firstAttackTeamId"] = first_attack
    next_round(w)
    return w


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


def next_round(w):
    if w["events"]:
        w["archive"].append(w["events"])
    n = w["round"] + 1
    half, ot = RULES["half"], RULES["overtimeHalf"]
    period = (n - 1) // half if n <= 2 * half else 2 + (n - 1 - 2 * half) // ot
    swaps = period if n <= 2 * half else 1 + ((n - 1 - 2 * half) // ot + 1) // 2
    reset = n in (1, half + 1) or (n > 2 * half and (n - 1 - 2 * half) % ot == 0)
    w.update(
        round=n,
        phase="freeze",
        deadline=w["tick"] + RULES["freeze"],
        events=[],
        action=None,
        bomb=dict(carrier=None, site=None, x=None, y=None),
        effects=[],
        recentEffects=[],
        traces=[],
        messages=[],
        kills=[],
        groundWeapons=[],
        plans={},
        clutch={},
        roundStart=w["tick"],
    )
    if reset:
        w["streak"] = [1, 1] if w.get("mapId") else [0, 0]
        if w.get("mapId"):
            w["opponentEconomy"] = {}
    space = cs2_maps.for_match(w)
    for a in w["agents"]:
        side = (
            "T" if (a["teamId"] == w["firstAttackTeamId"]) != bool(swaps % 2) else "CT"
        )
        slot = a["slot"]
        if space:
            (x,y,z),heading,area = space.spawn(side,slot,(w["seed"]+n) % len(space.spawns[side]))
            a.update(z=z,navArea=area,waypoint=0,blockedTicks=0,inspectedSites={},routeReports={},lastRouteReport=-100,
                     useTarget=None,useFloor=None,checkContact=None,checkPosition=None,
                     shelter=None,coverUntil=0,coverReview=0,bombSearch=None,coveredDefuser=None,coverPoint=None,revisedApproach=None,
                     rendezvous=None,plantCover=None,plantCheck=None,watchDevice=None,heardUse=-1000,
                     seenDevice=None,beepBearing=None,plantCue=None,leftScreen=False,sectorReview=None,incoming=None,pressureCall=None,nextPressureCall=0,sectorCalls={},squadPressure={},screenedOpening=False,friendlyUtility=[])
        else:
            x, y = engine._center(engine._SPAWN_CELLS[side][slot])
            heading=0 if side=="T" else atan2(0,-1)
        for key in ("audioCalls","lastDutyFeedback"):
            a.pop(key, None)
        a.pop("postWatch", None)
        if reset or not a["hp"]:
            a.update(
                weapon="Glock" if side == "T" else "USP",
                holster=None,
                armor=0,
                helmet=False,
                kit=False,
                utility=[],
            )
        elif a["holster"]:
            spare = a["holster"]["weapon"]
            if spare not in SIDEARMS:
                a.update(holster=match_inventory.stocked(a["weapon"]), weapon=spare)
            else:
                a["holster"] = match_inventory.stocked(spare)
        if reset:
            a["team"] = side
            money(
                w,
                a,
                (RULES["startMoney"] if n <= 2 * half else RULES["overtimeMoney"])
                - a["cash"],
                "Старт половины",
            )
        a.update(
            team=side,
            x=x,
            y=y,
            hp=100,
            status="Подготовка",
            heading=heading,
            ammo=WEAPONS[a["weapon"]].mag,
            reserve=WEAPONS[a["weapon"]].mag * 3,
            visible=[],
            knowledge={},
            path=[],
            dest=[],
            attackers={},
            blind=0,
            ready=0,
            throwAt=0,
            reloadAt=0,
            lastShot=-100,
            burst=0,
            target=None,
            heardSite=None,
            saving=None,
            approached=None,
        )
        init_performance(a, w["tick"])
        if side == "T" and slot == 2:
            w["bomb"]["carrier"] = a["id"]
    emit(w, "round_start", f"Раунд {n} · закупка", period=period, reset=reset)
    if w["pending"]:
        enter_timeout(w)


def purchase(w, a, item, give=None):
    price = WEAPONS[item].price if item in WEAPONS else PRICES[item]
    if price > a["cash"] or (item == "Шлем" and (not a["armor"] or a["helmet"])):
        return False
    money(w, a, -price, f"Покупка · {item}")
    recipient = give or a
    if item in WEAPONS:
        match_inventory.equip(recipient, match_inventory.stocked(item))
    elif item == "Броня":
        a["armor"] = 100
    elif item == "Шлем":
        a["helmet"] = True
    elif item == "Набор":
        a["kit"] = True
    else:
        a["utility"].append(item)
    emit(
        w,
        "buy",
        f"{a['name']} · {item}" + (f" для {recipient['name']}" if give else ""),
        a["team"],
        player=a["id"],
        item=item,
        recipient=recipient["id"],
        price=price,
    )
    return True


def buy_context(w, squad, call=None):
    if w.get("mapId"):
        return cs2_economy.decision(w, squad, call, profile=cs2_maps.PROFILES[w["mapId"]])["scenario"]
    average = sum(a["cash"] for a in squad) / len(squad)
    if call == "Экономить":
        return "Эко"
    if w["round"] in (1, RULES["half"] + 1):
        return "Пистолетная"
    return "Полная" if average >= 3600 else "Форс" if average >= 1900 else "Эко"


def board_buy(buy):
    return "Оружейная" if buy in ("Полная", "Форс") else buy


def board_categories(w, buy):
    if w.get("mapId"):
        return (buy,) if buy in ("Эко","Пистолетная") else (buy,"Оружейная")
    return (board_buy(buy),)


def next_buy(w, squad):
    if w.get("nextBoard"):
        return "Эко" if w["nextBoard"]["buy"] == "Эко" else buy_context(w, squad)
    return buy_context(w, squad, w.get("call"))


def assign(w, board):
    check_coach(w)
    board = deepcopy(tactics.validate(board) | tactics.reference(board))
    if board["map"]!=w.get("mapId","depo") or board["geometry"]!=w["map_version"]:
        raise ValueError("Тактика создана для другой карты или версии геометрии")
    side, buy = board["side"], board["buy"]
    if w["phase"] == "timeout":
        squad = [a for a in w["agents"] if a["teamId"] == w["coachTeamId"]]
        if side != squad[0]["team"] or buy not in board_categories(w, next_buy(w, squad)):
            raise ValueError(
                "Тактика не соответствует стороне или закупке ближайшего раунда"
            )
        w.update(nextBoard=board, call=board["name"])
    elif (
        w["round"] == 1
        and w["tick"] == 0
        and w["phase"] == "freeze"
        and not w.get("started")
        and w["remaining"] == w.get("openingTimeouts", RULES["timeouts"])
    ):
        w.setdefault("playbook", {})[side + "/" + buy] = board
    else:
        raise ValueError(
            "Назначение возможно до старта матча или в свой тактический тайм-аут"
        )
    emit(
        w,
        "board_call",
        f"Назначена тактика «{board['name']}» · в{board['revision']}",
        match_score.side_for(w, w["coachTeamId"]),
        tactic=tactics.reference(board),
    )


def begin_live(w):
    space=cs2_maps.for_match(w)
    now = w["tick"]
    for side in ("T", "CT"):
        squad = [a for a in w["agents"] if a["team"] == side]
        igl = next(a for a in squad if a["appointed"])
        call = w["call"] if igl["teamId"] == w["coachTeamId"] else None
        board = None
        if igl["teamId"] == w["coachTeamId"]:
            board = w.pop("nextBoard", None)
            if board:
                call = "Экономить" if board["buy"] == "Эко" else None
        buy = buy_context(w, squad, call)
        if space and board and w.get("previewBuy"):
            buy = w["previewBuy"]
        if (
            igl["teamId"] == w["coachTeamId"]
            and not board
            and call in (None, "Экономить")
        ):
            book = w.get("playbook", {})
            board = next((book[side + "/" + key] for key in board_categories(w,buy) if side + "/" + key in book),None)
        site = "AB"[(engine._draw(igl) >> 16) % 2]
        if call in ("Выход A", "Выход B"):
            site = call[-1]
        style = (
            "Быстро"
            if call == "Ускориться"
            or (engine._draw(igl) >> 16) % 100
            < 20 + profile(w, igl)["skills"]["aggression"] * 0.6
            else "Сбор"
        )
        if board:
            plant = next(
                (s for steps in board["slots"] for s in steps if s["kind"] == "plant"),
                None,
            )
            if plant:
                site = space.site_at(ai.point(plant)) if space else tactics.zone_at(plant["x"], plant["y"])
        lane=0
        if space:
            # Pick the budget once after choosing the board and intended site.
            # Its label, role orders, wallet limits and the emitted call must agree.
            requested = None
            if board:
                requested = w.get("previewBuy") or board["buy"]
            strategy = cs2_economy.decision(
                w, squad, call, site=site, profile=space.profile, board=board, requested=requested
            )
            buy = strategy["scenario"]
            site,style,lane=ai.cs2_play.opening(space,w,squad,igl,profile(w,igl),buy,site,style,call)
            if board and plant:
                site=space.site_at(ai.point(plant))
        w["plans"][side] = dict(
            site=site,
            style=style,
            buy=buy,
            start=now,
            review=now,
            rotated=False,
            orders=space.orders(side,site,squad,lane,style) if space else role_orders(side, site),
            captain=igl["id"],
            reinforce=site if side == "CT" and call in ("Выход A", "Выход B") else None,
        )
        if space:
            plan = w["plans"][side]
            plan["lane"] = lane
            if side == "CT" and not board:
                predicted = ai.cs2_play.defensive_read(w, igl) if not call else None
                site = plan["site"] = predicted or site
                style = cs2_openings.draft(
                    space,
                    plan,
                    squad,
                    w["domain"]["players"],
                    igl,
                    predicted,
                    plan["reinforce"],
                    w["domain"]["chemistry"],
                )
            if side == "T" and not board and style in ("Сбор", "Контроль карты"):
                plan["probe"] = ai.cs2_play.default_probe(space, squad, w["bomb"]["carrier"], plan, now, w["domain"])
        emit(
            w,
            "plan",
            f"{igl['name']} · {style}, {site} · {buy}",
            side,
            player=igl["id"],
            site=site,
            style=style,
            buy=buy,
        )
        for a in squad:
            a.update(
                liveStart=now,
                dayRoll=(engine._draw(a) >> 16) % 17 - 8,
                pressure=int(
                    max(w["score"]) >= RULES["half"]
                    and abs(w["score"][0] - w["score"][1]) <= 2
                ),
            )
        if board:
            w["plans"][side]["board"] = board
            emit(
                w,
                "board",
                f"{igl['name']} вызывает «{board['name']}» · в{board['revision']}",
                side,
                tactic=tactics.reference(board),
            )
            for a in squad:
                steps = board["slots"][a["slot"]]
                a.update(stepIndex=0, stepUntil=None)
                if any(s["kind"] == "plant" for s in steps):
                    w["bomb"]["carrier"] = a["id"]
                if space:
                    continue
                for item in (
                    tactics.equipment(steps) - Counter(a["utility"])
                ).elements():
                    if len(a["utility"]) < 2:
                        purchase(w, a, item)
        if space:
            # The captain can switch sites during the opening call. Give each role
            # the utility for the final approach within its agreed spending limit.
            strategy["needs"] = {
                a["id"]: cs2_economy.items_for(a, site, space.profile, board)
                for a in squad
            }
            w["plans"][side]["economy"] = strategy
            if opening := plan.get("opening"):
                for actor in squad:
                    task = opening["jobs"][actor["id"]]
                    if opening["quiet"] or task["zone"] not in opening["focus"]:
                        continue
                    wanted = cs2_openings.priority(task)
                    existing = strategy["needs"][actor["id"]]
                    strategy["needs"][actor["id"]] = (
                        wanted + [g for g in existing if g not in wanted]
                    )[:4]
            cs2_economy.buy(w, squad, strategy, purchase, board)
            if plan.get("opening"):
                cs2_openings.equip(space, plan, squad)
            continue
        rifle = "AK-47" if side == "T" else "M4A1-S"
        smg = "MAC-10" if side == "T" else "MP9"
        for a in squad:
            if buy in ("Полная", "Форс") and a["weapon"] in SIDEARMS:
                s = profile(w, a)["skills"]
                best = rifle
                if a["playingRole"] == "awper" and a["cash"] >= 5400:
                    best = "AWP"
                elif (
                    buy == "Форс"
                    and max(s["shotguns"], s["machine_guns"]) > s["rifles"]
                ):
                    best = "Nova" if s["shotguns"] > s["machine_guns"] else "Negev"
                if not purchase(w, a, best):
                    purchase(w, a, smg)
        for a in squad:
            if buy != "Эко" and a["weapon"] in SIDEARMS:
                donor = max(squad, key=lambda p: p["cash"])
                if (
                    donor["weapon"] not in SIDEARMS
                    and donor["cash"] >= WEAPONS[rifle].price + 650
                ):
                    purchase(w, donor, rifle, a)
            if buy == "Форс" and a["weapon"] in ("USP", "Glock"):
                purchase(w, a, "Desert Eagle")
            if buy != "Эко":
                if a["armor"] < 45 and (buy != "Пистолетная" or a["slot"] < 3):
                    purchase(w, a, "Броня")
                if buy in ("Полная", "Форс") and a["armor"] and not a["helmet"]:
                    purchase(w, a, "Шлем")
                if side == "CT" and not a["kit"] and a["slot"] in (0, 2, 4):
                    purchase(w, a, "Набор")
                order = ["Дым", "Свет", "HE", "Огонь", "Ложная"]
                if space:
                    order = ai.cs2_play.utility_buy(a,squad,w["plans"][side],profile(w,a)["skills"])
                else:
                    first = (a["slot"] + w["round"]) % len(order)
                    order = order[first:] + order[:first]
                for item in order:
                    if len(a["utility"]) >= 2:
                        break
                    if item not in a["utility"]:
                        purchase(w, a, item)
        if buy == "Эко":
            event = emit(
                w,
                "budget",
                f"{igl['name']} предлагает сохранить деньги",
                side,
                player=igl["id"],
            )
            igl["evidence"] = dict(
                id=event["id"],
                round=w["round"],
                text="Мы играли эко. Предлагаю согласовать следующую закупку.",
            )
    w.update(call=None, phase="live", deadline=now + RULES["live"])


def enter_timeout(w):
    if w["remaining"] <= 0:
        raise ValueError("Все три тайм-аута использованы")
    w.update(
        phase="timeout",
        pending=False,
        remaining=w["remaining"] - 1,
        feedback=[
            dict(player=a["name"], **a["evidence"])
            for a in w["agents"]
            if a["teamId"] == w["coachTeamId"] and a["evidence"]
        ],
    )
    emit(
        w,
        "timeout",
        f"{w['domain']['teams'][w['coachTeamId']]['name']} берёт тактический тайм-аут",
    )


def command(w, kind, value=None):
    check_coach(w)
    if w["phase"] == "finished":
        raise ValueError("Матч завершён")
    if kind == "timeout":
        if w["remaining"] <= 0 or w["pending"] or w["phase"] == "timeout":
            raise ValueError("Тайм-аут недоступен")
        if w["phase"] == "freeze":
            enter_timeout(w)
        else:
            w["pending"] = True
            emit(
                w,
                "request",
                f"{w['domain']['teams'][w['coachTeamId']]['name']} запросил тайм-аут на следующий раунд",
            )
    elif w["phase"] != "timeout":
        raise ValueError("Колл разрешён только в собственный тактический тайм-аут")
    elif kind == "call" and value in CALLS:
        w.pop("nextBoard", None)
        w["call"] = value
        emit(
            w,
            "call",
            f"Указание на следующий раунд · {value}",
            match_score.side_for(w, w["coachTeamId"]),
        )
    elif kind == "resume":
        w.update(phase="freeze", deadline=w["tick"] + RULES["freeze"])
        emit(w, "resume", "Тайм-аут завершён")
    else:
        raise ValueError("Неизвестное указание")


def finish_round(w, side, reason):
    if w["phase"] in ("result", "finished"):
        return
    winner_id, winner = match_score.award(w, side)
    emit(
        w,
        "round_end",
        f"{team(w, winner)['name']} · {reason}",
        winner=winner,
        winnerTeamId=winner_id,
        side=side,
        reason=reason,
    )
    if w.get("mapId") and "T" in w["plans"]:
        attack = next(a["teamId"] for a in w["agents"] if a["team"]=="T")
        history=w.setdefault("siteHistory",{}).setdefault(attack,[])
        history.append([w["plans"]["T"]["site"],side=="T"])
        del history[:-6]
        guards = [a for a in w["agents"] if a["team"] == "CT"]
        identified = next((a["heardSite"] for a in guards if a.get("heardSite")), None)
        defence = w.setdefault("defensiveHistory", {}).setdefault(guards[0]["teamId"], [])
        defence.append(identified)
        del defence[:-4]
    kills = w["kills"]
    for a in w["agents"]:
        player = profile(w, a)
        player["fatigue"] = perf.next_fatigue(player, a["movingTicks"])
        ident = a["id"]
        contributed = a["hp"] > 0 or any(
            (ident == k["player"] and k["enemy"])
            or ident in k["assists"]
            or ident == k["trade"]
            for k in kills
        )
        w["stats"][ident]["kast"] += int(contributed)
        if a["team"] == side:
            money(
                w,
                a,
                (
                    RULES["objectiveWin"]
                    if reason in ("Взрыв C4", "Обезвреживание")
                    else RULES["win"]
                ),
                "Победа",
            )
        elif not (a["team"] == "T" and a["hp"] and reason == "Время"):
            bonus = min(
                RULES["lossMax"],
                RULES["lossBase"] + RULES["lossStep"] * w["streak"][a["club"]],
            )
            money(w, a, bonus, "Поражение")
            if a["team"] == "T" and w["bomb"]["site"]:
                money(w, a, 600 if w.get("mapId") else RULES["plantBonus"], "Установка в проигранном раунде")
    if w.get("mapId"):
        ct_ids = {p["id"] for p in w["agents"] if p["team"]=="CT"}
        bonus = 50 * sum(k["enemy"] and k["player"] in ct_ids for k in kills)
        if bonus:
            for p in w["agents"]:
                if p["id"] in ct_ids:
                    money(w,p,bonus,"Командная награда за устранения CT")
        cs2_economy.update_opponents(w,side,reason)
    if side in w["clutch"]:
        w["stats"][w["clutch"][side]]["clutches"] += 1
    w["history"].append(
        dict(
            round=w["round"],
            winner=winner,
            winnerTeamId=winner_id,
            side=side,
            reason=reason,
            score=list(w["score"]),
            scoreByTeam=w["scoreByTeam"].copy(),
            duration=w["tick"] - w["roundStart"],
            economy=checkpoints.purchases(w["events"]),
        )
    )
    for plan in w["plans"].values():
        if plan.get("board"):
            w["history"][-1]["tactic"] = tactics.reference(plan["board"])
    if w.get("mapId"):
        w["streak"][winner] = max(0,w["streak"][winner]-1)
        w["streak"][1-winner] = min(4,w["streak"][1-winner]+1)
    else:
        w["streak"][winner] = 0
        w["streak"][1 - winner] += 1
    n = w["round"]
    half, ot = RULES["half"], RULES["overtimeHalf"]
    target = (
        half + 1
        if n <= half * 2
        else half + ot * (1 + (n - 2 * half - 1) // (2 * ot)) + 1
    )
    finished = w["scoreByTeam"][winner_id] >= target
    w.update(
        phase="finished" if finished else "result",
        deadline=w["tick"] + RULES["result"],
        action=None,
    )
    if finished:
        w["pending"] = False
        w["winnerTeamId"] = winner_id
        emit(
            w,
            "match_end",
            f"{team(w, winner)['name']} выиграл BO1",
            winner=winner,
            winnerTeamId=winner_id,
        )


def objective(w, a, kind, site=None):
    space=cs2_maps.for_match(w)
    if space:
        if kind=="plant":
            site=space.site_at(ai.point(a))
            if not site or w["bomb"]["carrier"]!=a["id"]:
                return
        elif ai.distance(a,w["bomb"])>6 or not space.clear(a,w["bomb"]):
            return
    now = w["tick"]
    if w["action"] is None:
        duration = (
            RULES["plant"]
            if kind == "plant"
            else RULES["kitDefuse"] if a["kit"] else RULES["defuse"]
        )
        w["action"] = dict(
            player=a["id"], kind=kind, site=site, start=now, end=now + duration
        )
        if space and kind == "plant":
            ai.cs2_play.hear_plant(space, w["agents"], a, now)
        if space and kind == "defuse":
            ai.cs2_play.hear_c4_use(space,w["agents"],w["bomb"],now)
        a["status"] = "Ставит C4" if kind == "plant" else "Обезвреживает"
        emit(
            w,
            kind + "_start",
            a["name"] + " · " + a["status"],
            a["team"],
            player=a["id"],
        )
    action = w["action"]
    if action["player"] != a["id"] or now < action["end"]:
        return
    if action["kind"] == "plant":
        w["bomb"].update(carrier=None, site=action["site"], **ai.at(ai.point(a)))
        w.update(phase="planted", deadline=now + RULES["fuse"], action=None)
        money(w, a, RULES["planter"], "Установка C4")
        emit(w, "plant", f"{a['name']} установил C4", player=a["id"])
    else:
        money(w, a, RULES["defuser"], "Обезвреживание C4")
        emit(w, "defuse", f"{a['name']} обезвредил C4", player=a["id"])
        finish_round(w, "CT", "Обезвреживание")


def resolve_attacks(w, order, players, ids, space):
    now = w["tick"]
    for a, kind, target in order:
        if not a["hp"] or kind not in ("shoot", "throw"):
            continue
        if kind == "throw":
            ai.throw(w, a, target, space)
        else:
            victim = ids.get(target.get("id"))
            if space and "id" not in target:
                # Collision is resolved by the world after all players commit
                # their intents. An empty aim point consumes the same shot.
                crossed = (p for p in players if p is not a and p["hp"] and
                           ai.near_line(a,target,p,3))
                victim = min(crossed,key=lambda p: ai.distance(a,p),default=None)
            ai.shoot(w, a, target, victim, space)
            if space and a["team"] == "T" and w["phase"] == "live":
                radius = 75 if a["weapon"] in ("USP", "M4A1-S") else 128
                ai.heard_action(w,space,a,players,"Выстрел",radius)
            for listener in players:
                # A passing shot is perceptible at the listener, even when the
                # shooter is outside their vision or normal local audio radius.
                if (space and listener is not a and listener["hp"] and
                        a["id"] not in listener["visible"] and
                        ai.near_line(a,target,listener,6) and
                        space.hit(ai.point(a),ai.point(listener),4,56) is None):
                    listener["incoming"] = dict(tick=now,bearing=ai.cs2_play.sound_bearing(listener,a))
                    if now >= listener.get("nextPressureCall",0):
                        delay = ai.radio_delay(profile(w,listener)["skills"])
                        listener.setdefault("squadPressure",{})[listener["id"]] = dict(listener["incoming"],origin=list(ai.point(listener)))
                        listener["nextPressureCall"] = now + 10 + delay
                        w["messages"].append(dict(team=listener["team"],sender=listener["id"],
                            pressure=dict(listener["incoming"],origin=list(ai.point(listener))),
                            due=now+delay))
                if (
                    listener["team"] != a["team"]
                    and listener["hp"]
                    and a["id"] not in listener["visible"]
                    and not (space and listener["team"] == "CT" and w["phase"] == "live")
                    and ai.distance(a, listener) < 55
                ):
                    # Sound identifies a sector, never a tracked live enemy position.
                    p = ai.sound_position(space,a)
                    key = "Шум"
                    cue = dict(id=key, **p, tick=now, source="Слух")
                    listener["knowledge"][key] = cue
                    if space and now >= listener.get("nextSoundCall", 0):
                        delay = ai.radio_delay(profile(w, listener)["skills"])
                        listener["nextSoundCall"] = now + 10 + delay
                        w["messages"].append(dict(team=listener["team"], sender=listener["id"],
                                                  sight=cue, due=now+delay))


def advance(w):
    if w["phase"] in ("finished", "timeout"):
        return
    if w["rules"] in cs2_maps.SUPPORTED_RULES[1:]:
        w["rulesTransition"] = dict(previous=w["rules"], tick=w["tick"], lastEvent=w["serial"])
        w["rules"] = cs2_maps.RULES
    # Preserve the initiative and utility ordering after restoring a reordered collection.
    w["agents"].sort(key=lambda a: (a["teamId"] != w["firstAttackTeamId"], a["slot"]))
    w["started"] = True
    w["tick"] += 1
    now = w["tick"]
    if w["phase"] == "freeze":
        if now >= w["deadline"]:
            begin_live(w)
        return
    if w["phase"] == "result":
        if now >= w["deadline"]:
            next_round(w)
        return
    ids = {a["id"]: a for a in w["agents"]}
    space=cs2_maps.for_match(w)
    ai.apply_effects(w, ids, space)
    players = [a for a in ids.values() if a["hp"]]
    ai.observe(w, players, space)
    bomb = w["bomb"]
    w["traces"] = [t for t in w["traces"] if now - t["tick"] < 45]
    intents = []
    for side in ("T", "CT"):
        squad = [a for a in players if a["team"] == side]
        if not squad:
            continue
        ai.captain(w, squad, space)
        recovery = ai.cs2_play.rescue(space, squad, bomb) if space and side == "T" else None
        for a in squad:
            picked = match_inventory.take_nearby(w, a, space)
            if picked:
                emit(
                    w,
                    "weapon_pickup",
                    f"{a['name']} подобрал {picked['weapon']}",
                    side,
                    player=a["id"],
                    weapon=picked["weapon"],
                    dropId=picked["id"],
                )
            known_bomb = bomb if side == "T" else a.get("seenDevice")
            if side == "CT" and bomb["site"] and ai.distance(a, bomb) < 72:
                if not a["heardSite"]:
                    a["heardSite"] = bomb["site"]
                    w["messages"].append(
                        dict(
                            team=side,
                            sender=a["id"],
                            site=bomb["site"],
                            due=now + ai.radio_delay(profile(w, a)["skills"]),
                        )
                    )
                if space:
                    ai.cs2_play.hear_device(a, bomb, now)
                if (known_bomb is None and ai.distance(a, bomb) < 30 and ai.clear(space, a, bomb)):
                    if space is None:
                        known_bomb = bomb
                    elif a["blind"] <= now and not any(
                        fog["kind"] == "Дым" and fog["land"] <= now < fog["end"]
                        and ai.near_line(a, bomb, fog, fog["radius"])
                        for fog in w["effects"]
                    ):
                        known_bomb = {k: bomb[k] for k in ("x", "y", "z", "site", "carrier")}
                        a["seenDevice"] = known_bomb
                        w["messages"].append(dict(
                            team=side, sender=a["id"], device=known_bomb,
                            due=now + ai.radio_delay(profile(w, a)["skills"]),
                        ))
            if (
                side == "T"
                and not bomb["carrier"]
                and not bomb["site"]
                and ai.distance(a, bomb) <= 7
                and (space is None or space.clear(a, bomb))
            ):
                bomb["carrier"] = a["id"]
                emit(w, "pickup", f"{a['name']} поднял C4", "T", player=a["id"])
            fire = [
                f
                for f in w["effects"]
                if f["kind"] == "Огонь"
                and f["land"] <= now
                and ai.distance(a, f) < 70
                and ai.clear(space,a,f)
            ]
            observation = dict(
                space=space,
                recovery=recovery,
                tick=now,
                player=profile(w, a),
                chemistry=w["domain"]["chemistry"],
                phase=w["phase"],
                deadline=w["deadline"],
                plan=w["plans"][side],
                action=(
                    w["action"]
                    if w["action"] and ids[w["action"]["player"]]["team"] == side
                    else None
                ),
            )
            if (
                side == "CT"
                and w["phase"] == "live"
                and (opening := observation["plan"].get("opening"))
            ):
                job = opening["jobs"][a["id"]]
                if "peek" in job and ai.distance(a, ai.at(job["peek"])) < 6:
                    sight = ai.at(job["watch"])
                    observation["openingSight"] = space.clear(a, sight) and not any(
                        f["kind"] == "Дым"
                        and f["land"] <= now < f["end"]
                        and ai.near_line(a, sight, f, f["radius"])
                        for f in w["effects"]
                    )
            previous = a["status"]
            step_index = a.get("stepIndex", 0)
            prior_position = cs2_maps.xyz(a) if space and side == "T" and w["phase"] == "live" else None
            intents.append((a, *ai.act(observation, a, squad, known_bomb, fire)))
            if space:
                ai.cs2_play.cs2_defense.check_incoming(
                    a, intents[-1][1], now, observation["player"]["skills"]
                )
            if space and a.get("lastBlockedTick") != now:
                a["blockedTicks"] = 0
            if (space and side=="T" and w["phase"]=="live" and a.get("blockedTicks",0)>=20
                    and now-a.get("lastRouteReport",-100)>=60):
                site=w["plans"][side]["site"]
                a["lastRouteReport"]=now
                a.setdefault("routeReports",{})[a["id"]]=[site,now]
                w["messages"].append(dict(team=side,sender=a["id"],blockedSite=site,
                                          due=now+ai.radio_delay(profile(w,a)["skills"])))
            if space and side == "CT" and w["phase"] == "live" and now % 5 == a["slot"]:
                call = ai.cs2_play.cs2_defense.duty_feedback(
                    w["plans"]["CT"], a, squad, now
                )
                if call:
                    ai.send_sector(w, a, call)
            if intents[-1][1] == "move":
                if (
                    prior_position
                    and now % 5 == a["slot"]
                    and ai.dist(prior_position, cs2_maps.xyz(a)) > 0.9
                ):
                    ai.heard_action(w, space, a, players, "Шаги", 88)
                a["lastMove"] = now
                a["movingTicks"] += 1
            if observation["plan"].get("board"):
                if a["stepIndex"] != step_index:
                    emit(
                        w,
                        "board_step",
                        f"{a['name']} · {a['status']}",
                        side,
                        player=a["id"],
                        step=step_index,
                    )
                elif previous != a["status"] and a["status"] in (
                    "К капитану после потери союзника",
                    "Пережидает огонь за укрытием",
                    "Обходит огонь",
                    "Подбирает C4",
                ):
                    emit(
                        w, "adapt", f"{a['name']} · {a['status']}", side, player=a["id"]
                    )
            if a["reloadAt"] == now + WEAPONS[a["weapon"]].reload:
                emit(
                    w,
                    "reload",
                    f"{a['name']} перезаряжает {a['weapon']}",
                    side,
                    weapon=a["weapon"],
                    player=a["id"],
                )
    resolve_intents(w, intents, players, ids, space)


def resolve_intents(w, intents, players, ids, space):
    now, bomb = w["tick"], w["bomb"]
    # Alternate initiative on a tick. A dead or newly occluded target cannot be hit.
    order = intents if now % 2 else intents[::-1]
    resolve_attacks(w, order, players, ids, space)
    action = w["action"]
    if action and not any(
        a["hp"] and a["id"] == action["player"] and kind == "objective"
        for a, kind, _ in intents
    ):
        emit(
            w,
            "interrupt",
            "Действие с C4 прервано",
            ids[action["player"]]["team"],
            player=action["player"],
        )
        w["action"] = None
    # On the exact deadline, expiry precedes completion. Eliminations precede use.
    living = {
        s: [a for a in players if a["hp"] and a["team"] == s] for s in ("T", "CT")
    }
    if w["phase"] == "planted" and now >= w["deadline"]:
        emit(w, "explode", "C4 взорвалась")
        for a in players:
            dist = ai.distance(a, bomb)
            if a["hp"] and blast_damage(dist):
                impact(w, a, a, blast_damage(dist), "C4", "blast")
        finish_round(w, "T", "Взрыв C4")
    elif not living["CT"] and not living["T"] and w["phase"] == "live":
        # Simultaneous utility on this tick still has an ordered death ledger.
        last_victim = ids[w["kills"][-1]["target"]]
        finish_round(w, last_victim["team"], "Устранение")
    elif not living["CT"]:
        finish_round(w, "T", "Устранение")
    elif w["phase"] == "live" and not living["T"]:
        finish_round(w, "CT", "Устранение")
    elif w["phase"] == "live" and now >= w["deadline"]:
        finish_round(w, "CT", "Время")
    else:
        for side in living:
            other = "T" if side == "CT" else "CT"
            if len(living[side]) == 1 and living[other]:
                w["clutch"].setdefault(side, living[side][0]["id"])
        for a, kind, target in order:
            if not a["hp"]:
                continue
            if kind == "objective" and w["action"]:
                objective(w, a, w["action"]["kind"])
            elif kind == "defuse" and w["phase"] == "planted":
                objective(w, a, kind)
            elif kind == "plant" and w["phase"] == "live":
                objective(w, a, kind, target)
            if w["phase"] in ("result", "finished"):
                break

    # A move, flash or death can close a sight line during this very step.
    # Neither the final projection nor sub-tick motion tracks may reveal it.
    smoke = [f for f in w["effects"] if f["kind"] == "Дым" and f["land"] <= now]
    for a in players:
        a["visible"] = [
            ident
            for ident in a["visible"]
            if a["hp"]
            and ids[ident]["hp"]
            and a["blind"] <= now
            and ai.sees(space,a,ids[ident])
            and not any(ai.near_line(a, ids[ident], f, f["radius"]) for f in smoke)
        ]


def project(w, view="full"):
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
        agents.append(marker)
    bomb = w["bomb"]
    carrier = next((a for a in w["agents"] if a["id"] == bomb["carrier"]), None)
    point = carrier or bomb
    smoke = [f for f in w["effects"] if f["kind"] == "Дым" and f["land"] <= w["tick"]]

    def observable(p, *, cloud=False):
        return view == "full" or any(
            a["hp"]
            and a["blind"] <= w["tick"]
            and ai.sees(space,a,p)
            and not any(
                ai.near_line(a, p, f, f["radius"]) for f in smoke if not cloud or f != p
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
            **ai.at(ai.point(point)), carrier=bomb["carrier"], site=bomb["site"]
        )
    effects = [
        f
        for f in w["recentEffects"]
        if view in ("full", f["team"])
        or (w["tick"] >= f["land"] and observable(f, cloud=f["kind"] == "Дым"))
    ]
    # Do not reveal an unseen thrower's origin via the trajectory of a landed grenade.
    effects = [
        f if view in ("full", f["team"]) else dict({k:v for k,v in f.items() if k not in ("trajectory","sz")}, sx=f["x"], sy=f["y"], player=None)
        for f in effects
    ]
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
        stats.append(row)
    audience = lambda e: view == "full" or e["team"] in (view, None)
    journal = [
        e
        for e in w["events"]
        if audience(e) and e["kind"] not in ("money", "buy", "shot", "damage")
    ]
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
    coach_view = coach_view and not w.get("series", {}).get("spectator")
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
            clock=max(0, w["deadline"] - w["tick"]),
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
                board_categories(w,
                    next_buy(
                        w, [a for a in w["agents"] if a["teamId"] == w["coachTeamId"]]
                    )
                )[0]
                if coach_view and (known is None or all(a["playerId"] in known for a in coached))
                else None
            ),
            remaining=w["remaining"],
            timeoutLimit=w.get("series",{}).get("profile",{}).get("timeouts",RULES["timeouts"]),
            pending=w["pending"],
            call=w["call"] if coach_view else None,
            calls=CALLS,
            feedback=w["feedback"] if coach_view and w["phase"] == "timeout" else [],
        ),
    )
