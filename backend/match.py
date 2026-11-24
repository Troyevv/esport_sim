"""Autonomous BO1. The same step drives the home server and headless matches."""

from collections import Counter
from copy import deepcopy
from math import atan2

from . import checkpoints, engine, tactics, world
from . import match_performance as perf
from . import match_ai as ai
from .match_events import damage, emit, money
from .match_rules import (
    CALLS,
    MAP,
    PRICES,
    ROLES,
    RULES,
    VERSION,
    WEAPONS,
    role_orders,
)


def profile(w, a):
    return w["domain"]["players"][a["playerId"]]


def team(w, club):
    data = w["domain"]
    return data["teams"][data["rosters"][w["rosterIds"][club]]["team"]]


def check_coach(w):
    world.authorize(w["domain"]["authority"], team(w, 0)["organization"], "coach_match")


def bind_rosters(w, data, roster_ids):
    world.validate(data)
    if len(roster_ids) != 2 or roster_ids[0] == roster_ids[1]:
        raise ValueError("Нужны два разных состава")
    w.update(domain=data, rosterIds=list(roster_ids))
    for club, roster in enumerate(roster_ids):
        for slot, member in enumerate(world.validate_five(data, roster)):
            a = w["agents"][club * 5 + slot]
            ident = member["player"]
            a.update(playerId=ident, playingRole=member["role"], appointed=member["captain"],
                     name=data["players"][ident]["name"])
    check_coach(w)


def init_performance(a, now):
    a.update(lastMove=-100, lastHurt=-100, previousTarget=None, observedSpeed=0,
             movingTicks=0, liveStart=now, dayRoll=0, pressure=0, stepReady=0, tradeTarget=None, tradeUntil=0)


def initial(seed, domain=None, roster_ids=world.FIXTURE_ROSTERS):
    w = engine.initial(seed)
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
    bind_rosters(w, world.exhibition(w["agents"]) if domain is None else deepcopy(domain), roster_ids)
    for i, a in enumerate(w["agents"]):
        a.update(
            club=i // 5,
            slot=i % 5,
            role=ROLES[i % 5],
            cash=0,
            hp=0,
            evidence=None,
        )
        w["stats"][a["id"]] = dict(
            k=0, d=0, a=0, hs=0, damage=0, opening=0, kast=0, spent=0, clutches=0
        )
    next_round(w)
    return w


def migrate_legacy(w):
    data = world.exhibition(w["agents"], legacy=True)
    bind_rosters(w, data, world.FIXTURE_ROSTERS)
    for a in w["agents"]:
        init_performance(a, w["plans"].get(a["team"], {}).get("start", w["tick"]))
        a["previousTarget"] = a["target"]
        for key in ("aim", "reaction", "comms", "tactics"):
            del a[key]
    w["rules"] = VERSION


def validate_bindings(w):
    data = w["domain"]
    world.validate(data)
    if len(w["rosterIds"]) != 2 or len(set(w["rosterIds"])) != 2 or len(w["agents"]) != 10:
        raise ValueError("Некорректный состав BO1")
    for club, roster in enumerate(w["rosterIds"]):
        for slot, m in enumerate(world.validate_five(data, roster)):
            a = w["agents"][club * 5 + slot]
            if (a["club"], a["slot"], a["playerId"], a["playingRole"], a["appointed"]) != (
                club, slot, m["player"], m["role"], m["captain"]
            ):
                raise ValueError("Участник матча расходится с заявленной пятёркой")
    check_coach(w)


def next_round(w):
    if w["events"]:
        w["archive"].append(w["events"])
    n = w["round"] + 1
    half, ot = RULES["half"], RULES["overtimeHalf"]
    period = (n - 1) // half if n <= 2 * half else 2 + (n - 1 - 2 * half) // ot
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
        plans={},
        clutch={},
        roundStart=w["tick"],
    )
    if reset:
        w["streak"] = [0, 0]
    for a in w["agents"]:
        side = "T" if (a["club"] + period) % 2 == 0 else "CT"
        slot = a["slot"]
        x, y = engine._center(engine._SPAWN_CELLS[side][slot])
        if reset or not a["hp"]:
            a.update(
                weapon="Glock" if side == "T" else "USP", armor=0, kit=False, utility=[]
            )
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
            heading=0 if side == "T" else atan2(0, -1),
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
    if price > a["cash"]:
        return False
    money(w, a, -price, f"Покупка · {item}")
    recipient = give or a
    if item in WEAPONS:
        weapon = WEAPONS[item]
        recipient.update(weapon=item, ammo=weapon.mag, reserve=weapon.mag * 3)
    elif item == "Броня":
        a["armor"] = 100
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
    average = sum(a["cash"] for a in squad) / len(squad)
    if call == "Экономить":
        return "Эко"
    if w["round"] in (1, RULES["half"] + 1):
        return "Пистолетная"
    return "Полная" if average >= 3600 else "Форс" if average >= 1900 else "Эко"


def board_buy(buy):
    return "Оружейная" if buy in ("Полная", "Форс") else buy


def next_buy(w, squad):
    if w.get("nextBoard"):
        return "Эко" if w["nextBoard"]["buy"] == "Эко" else buy_context(w, squad)
    return buy_context(w, squad, w.get("call"))


def assign(w, board):
    check_coach(w)
    board = deepcopy(tactics.validate(board) | tactics.reference(board))
    side, buy = board["side"], board["buy"]
    if w["phase"] == "timeout":
        squad = [a for a in w["agents"] if a["club"] == 0]
        if side != squad[0]["team"] or buy != board_buy(next_buy(w, squad)):
            raise ValueError(
                "Тактика не соответствует стороне или закупке ближайшего раунда"
            )
        w.update(nextBoard=board, call=board["name"])
    elif (
        w["round"] == 1
        and w["tick"] == 0
        and w["phase"] == "freeze"
        and not w.get("started")
        and w["remaining"] == RULES["timeouts"]
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
        w["agents"][0]["team"],
        tactic=tactics.reference(board),
    )


def begin_live(w):
    now = w["tick"]
    for side in ("T", "CT"):
        squad = [a for a in w["agents"] if a["team"] == side]
        igl = next(a for a in squad if a["appointed"])
        call = w["call"] if igl["club"] == 0 else None
        board = None
        if igl["club"] == 0:
            board = w.pop("nextBoard", None)
            if board:
                call = "Экономить" if board["buy"] == "Эко" else None
        buy = buy_context(w, squad, call)
        if igl["club"] == 0 and not board and call in (None, "Экономить"):
            board = w.get("playbook", {}).get(side + "/" + board_buy(buy))
        site = "AB"[(engine._draw(igl) >> 16) % 2]
        if call in ("Выход A", "Выход B"):
            site = call[-1]
        style = "Быстро" if call == "Ускориться" or (engine._draw(igl) >> 16) % 100 < 20 + profile(w, igl)["skills"]["aggression"] * .6 else "Сбор"
        if board:
            plant = next(
                (s for steps in board["slots"] for s in steps if s["kind"] == "plant"),
                None,
            )
            if plant:
                site = tactics.zone_at(plant["x"], plant["y"])
        w["plans"][side] = dict(
            site=site,
            style=style,
            buy=buy,
            start=now,
            review=now,
            rotated=False,
            orders=role_orders(side, site),
            captain=igl["id"],
            reinforce=site if side == "CT" and call in ("Выход A", "Выход B") else None,
        )
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
            a.update(liveStart=now, dayRoll=(engine._draw(a) >> 16) % 17 - 8,
                     pressure=int(max(w["score"]) >= RULES["half"] and abs(w["score"][0] - w["score"][1]) <= 2))
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
                for item in (
                    tactics.equipment(steps) - Counter(a["utility"])
                ).elements():
                    if len(a["utility"]) < 2:
                        purchase(w, a, item)
        rifle = "AK-47" if side == "T" else "M4A1-S"
        smg = "MAC-10" if side == "T" else "MP9"
        for a in squad:
            if buy in ("Полная", "Форс") and not WEAPONS[a["weapon"]].price:
                s = profile(w, a)["skills"]
                best = rifle
                if a["playingRole"] == "awper" and a["cash"] >= 5400:
                    best = "AWP"
                elif buy == "Форс" and max(s["shotguns"], s["machine_guns"]) > s["rifles"]:
                    best = "Nova" if s["shotguns"] > s["machine_guns"] else "Negev"
                if not purchase(w, a, best):
                    purchase(w, a, smg)
        for a in squad:
            if buy != "Эко" and not WEAPONS[a["weapon"]].price:
                donor = max(squad, key=lambda p: p["cash"])
                if (
                    WEAPONS[donor["weapon"]].price
                    and donor["cash"] >= WEAPONS[rifle].price + 650
                ):
                    purchase(w, donor, rifle, a)
            if buy != "Эко":
                if a["armor"] < 45 and (buy != "Пистолетная" or a["slot"] < 3):
                    purchase(w, a, "Броня")
                if side == "CT" and not a["kit"] and a["slot"] in (0, 2, 4):
                    purchase(w, a, "Набор")
                order = ["Дым", "Свет", "HE", "Огонь", "Ложная"]
                first = (a["slot"] + w["round"]) % len(order)
                for item in order[first:] + order[:first]:
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
            if a["club"] == 0 and a["evidence"]
        ],
    )
    emit(w, "timeout", f"{team(w, 0)['name']} берёт тактический тайм-аут")


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
            emit(w, "request", f"{team(w, 0)['name']} запросил тайм-аут на следующий раунд")
    elif w["phase"] != "timeout":
        raise ValueError("Колл разрешён только в собственный тактический тайм-аут")
    elif kind == "call" and value in CALLS:
        w.pop("nextBoard", None)
        w["call"] = value
        emit(
            w, "call", f"Указание на следующий раунд · {value}", w["agents"][0]["team"]
        )
    elif kind == "resume":
        w.update(phase="freeze", deadline=w["tick"] + RULES["freeze"])
        emit(w, "resume", "Тайм-аут завершён")
    else:
        raise ValueError("Неизвестное указание")


def finish_round(w, side, reason):
    winner = next(a["club"] for a in w["agents"] if a["team"] == side)
    event = emit(
        w,
        "round_end",
        f"{team(w, winner)['name']} · {reason}",
        winner=winner,
        side=side,
        reason=reason,
    )
    w["score"][event["winner"]] += 1
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
                RULES["objectiveWin"]
                if reason in ("Взрыв C4", "Обезвреживание")
                else RULES["win"],
                "Победа",
            )
        elif not (a["team"] == "T" and a["hp"] and reason == "Время"):
            bonus = min(
                RULES["lossMax"],
                RULES["lossBase"] + RULES["lossStep"] * w["streak"][a["club"]],
            )
            money(w, a, bonus, "Поражение")
            if a["team"] == "T" and w["bomb"]["site"]:
                money(w, a, RULES["plantBonus"], "Установка в проигранном раунде")
    if side in w["clutch"]:
        w["stats"][w["clutch"][side]]["clutches"] += 1
    w["history"].append(
        dict(
            round=w["round"],
            winner=winner,
            side=side,
            reason=reason,
            score=list(w["score"]),
            duration=w["tick"] - w["roundStart"],
            economy=checkpoints.purchases(w["events"]),
        )
    )
    for plan in w["plans"].values():
        if plan.get("board"):
            w["history"][-1]["tactic"] = tactics.reference(plan["board"])
    w["streak"][winner] = 0
    w["streak"][1 - winner] += 1
    n = w["round"]
    half, ot = RULES["half"], RULES["overtimeHalf"]
    target = (
        half + 1
        if n <= half * 2
        else half + ot * (1 + (n - 2 * half - 1) // (2 * ot)) + 1
    )
    finished = max(w["score"]) >= target
    w.update(
        phase="finished" if finished else "result",
        deadline=w["tick"] + RULES["result"],
        action=None,
    )
    if finished:
        w["pending"] = False
        emit(w, "match_end", f"{team(w, winner)['name']} выиграл BO1", winner=winner)


def objective(w, a, kind, site=None):
    now = w["tick"]
    if w["action"] is None:
        duration = (
            RULES["plant"]
            if kind == "plant"
            else RULES["kitDefuse"]
            if a["kit"]
            else RULES["defuse"]
        )
        w["action"] = dict(
            player=a["id"], kind=kind, site=site, start=now, end=now + duration
        )
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
        w["bomb"].update(carrier=None, site=action["site"], x=a["x"], y=a["y"])
        w.update(phase="planted", deadline=now + RULES["fuse"], action=None)
        money(w, a, RULES["planter"], "Установка C4")
        emit(w, "plant", f"{a['name']} установил C4", player=a["id"])
    else:
        money(w, a, RULES["defuser"], "Обезвреживание C4")
        emit(w, "defuse", f"{a['name']} обезвредил C4", player=a["id"])
        finish_round(w, "CT", "Обезвреживание")


def advance(w):
    if w["phase"] in ("finished", "timeout"):
        return
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
    ai.apply_effects(w, ids)
    players = [a for a in ids.values() if a["hp"]]
    ai.observe(w, players)
    bomb = w["bomb"]
    w["traces"] = [t for t in w["traces"] if now - t["tick"] < 45]
    intents = []
    for side in ("T", "CT"):
        squad = [a for a in players if a["team"] == side]
        if not squad:
            continue
        ai.captain(w, squad)
        for a in squad:
            known_bomb = bomb if side == "T" else None
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
                if ai.distance(a, bomb) < 30 and engine.clear_line(
                    a["x"], a["y"], bomb["x"], bomb["y"]
                ):
                    known_bomb = bomb
            if (
                side == "T"
                and not bomb["carrier"]
                and not bomb["site"]
                and ai.distance(a, bomb) <= 7
            ):
                bomb["carrier"] = a["id"]
                emit(w, "pickup", f"{a['name']} поднял C4", "T", player=a["id"])
            fire = [
                f
                for f in w["effects"]
                if f["kind"] == "Огонь"
                and f["land"] <= now
                and ai.distance(a, f) < 70
                and engine.clear_line(a["x"], a["y"], f["x"], f["y"])
            ]
            observation = dict(
                tick=now,
                player=profile(w, a),
                chemistry=w["domain"]["chemistry"],
                phase=w["phase"],
                deadline=w["deadline"],
                plan=w["plans"][side],
                action=w["action"]
                if w["action"] and ids[w["action"]["player"]]["team"] == side
                else None,
            )
            previous = a["status"]
            step_index = a.get("stepIndex", 0)
            intents.append((a, *ai.act(observation, a, squad, known_bomb, fire)))
            if intents[-1][1] == "move":
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
                    player=a["id"],
                )
    # Alternate initiative on a tick. A dead or newly occluded target cannot be hit.
    order = intents if now % 2 else intents[::-1]
    for a, kind, target in order:
        if not a["hp"] or kind not in ("shoot", "throw"):
            continue
        if kind == "throw":
            ai.throw(w, a, target)
        else:
            ai.shoot(w, a, target, ids[target["id"]])
            for listener in players:
                if (
                    listener["team"] != a["team"]
                    and listener["hp"]
                    and a["id"] not in listener["visible"]
                    and ai.distance(a, listener) < 55
                ):
                    # Sound identifies a sector, never a tracked live enemy position.
                    p = ai.audible_sector(a["x"] // 30, a["y"] // 30)
                    key = "Шум"
                    listener["knowledge"][key] = dict(
                        id=key, **p, tick=now, source="Слух"
                    )
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
            if a["hp"] and dist < 80:
                damage(w, a, a, max(1, round(370 * (1 - dist / 80))), "C4")
        finish_round(w, "T", "Взрыв C4")
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
            and engine.sees(a, ids[ident])
            and not any(ai.near_line(a, ids[ident], f, f["radius"]) for f in smoke)
        ]


def project(w, view="full"):
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
        marker.update(
            alive=bool(a["hp"]),
            status=a["status"] if friendly else "В поле зрения",
            visible=a["visible"] if friendly else [],
            knowledge=list(a["knowledge"].values()) if friendly else [],
        )
        if friendly:
            marker.update(playerId=a["playerId"])
            marker.update(
                {
                    k: a[k]
                    for k in (
                        "hp",
                        "armor",
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
            and engine.sees(a, p)
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
            x=point["x"], y=point["y"], carrier=bomb["carrier"], site=bomb["site"]
        )
    effects = [
        f
        for f in w["recentEffects"]
        if view in ("full", f["team"])
        or (w["tick"] >= f["land"] and observable(f, cloud=f["kind"] == "Дым"))
    ]
    # Do not reveal an unseen thrower's origin via the trajectory of a landed grenade.
    effects = [
        f if view in ("full", f["team"]) else dict(f, sx=f["x"], sy=f["y"], player=None)
        for f in effects
    ]
    stats = []
    for a in w["agents"]:
        row = dict(
            id=a["id"],
            name=a["name"],
            club=a["club"],
            team=a["team"],
            role=a["role"],
            **w["stats"][a["id"]],
        )
        if view not in ("full", a["team"]) and w["phase"] != "finished":
            row["spent"] = None
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
    coach_view = view in ("full", w["agents"][0]["team"])
    ratings = {}
    if coach_view:
        for a in w["agents"]:
            if a["club"] == 0:
                ratings[a["id"]] = world.player_report(w["domain"], a["playerId"])["ratings"]
    return dict(
        seed=w["seed"],
        tick=w["tick"],
        time=w["tick"] / 10,
        map=MAP,
        agents=agents,
        view=view,
        events=journal[-48:],
        match=dict(
            rules=w["rules"],
            roleRatings=ratings,
            teamRating=world.team_rating(w["domain"], w["rosterIds"][0], MAP["id"]) if coach_view else None,
            round=w["round"],
            phase=w["phase"],
            clock=max(0, w["deadline"] - w["tick"]),
            teams=[team(w, i)["name"] for i in (0, 1)],
            score=w["score"],
            sides=[w["agents"][i]["team"] for i in (0, 5)],
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
            resolution=next(
                (
                    dict(kind=e["kind"], tick=e["tick"])
                    for e in reversed(w["events"])
                    if e["kind"] in ("explode", "defuse")
                ),
                None,
            )
            if w["phase"] in ("finished", "result")
            else None,
            action=action,
            effects=effects,
            shots=[{k: v for k, v in e.items() if k != "accuracy"} for e in w["traces"] if audience(e)],
            kills=w["kills"][-8:],
            plans={
                s: {k: v for k, v in p.items() if k != "board"}
                | ({"tactic": tactics.reference(p["board"])} if "board" in p else {})
                for s, p in w["plans"].items()
                if view in ("full", s)
            },
            prepared=[tactics.reference(p) for p in w.get("playbook", {}).values()]
            if coach_view
            else [],
            pregame=not w.get("started")
            and w["tick"] == 0
            and w["phase"] == "freeze"
            and w["remaining"] == RULES["timeouts"],
            nextBuy=board_buy(next_buy(w, [a for a in w["agents"] if a["club"] == 0]))
            if coach_view
            else None,
            remaining=w["remaining"],
            timeoutLimit=RULES["timeouts"],
            pending=w["pending"],
            call=w["call"] if coach_view else None,
            calls=CALLS,
            feedback=w["feedback"] if coach_view and w["phase"] == "timeout" else [],
        ),
    )
