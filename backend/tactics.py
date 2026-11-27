"""Versioned role plans for the fictional Depo grid and the BO1 buy profiles."""

from collections import Counter
from random import Random

from math import isfinite
from . import cs2_maps, engine
from .match_rules import SCENARIOS, APPROACH, MAP, POSITIONS, PRICES, STAGING, UTILITY

LEGACY_BUYS = ("Пистолетная", "Эко", "Оружейная")
BUYS = (*LEGACY_BUYS, *(b for b in SCENARIOS if b not in LEGACY_BUYS))
MOVES = ("move", "hold", "exit", "plant", "retreat", "wait")
ACTIONS = (*MOVES, "face", "throw")
LABELS = dict(
    move="Маршрут",
    hold="Удержание",
    exit="Выход",
    plant="Установка",
    retreat="Отход",
    wait="Ожидание",
    face="Направление",
    throw="Граната",
)


def zone_at(x, y):
    return next(
        (
            z["name"]
            for z in MAP["zones"]
            if z["x"] <= x < z["x"] + z["w"] and z["y"] <= y < z["y"] + z["h"]
        ),
        None,
    )


def validate(plan):
    if (
        not isinstance(plan, dict)
        or type(plan.get("format")) is not int
        or plan["format"] not in (1,2)
    ):
        raise ValueError("Неизвестный формат тактики")
    ident = plan.get("map")
    space = cs2_maps.get(ident) if isinstance(ident,str) and ident in cs2_maps.NAMES else None
    if (ident, plan.get("geometry")) != ((space.name,cs2_maps.BUILD) if space else (MAP["id"], MAP["version"])):
        raise ValueError("Выбрана другая карта или версия геометрии")
    side, buy = plan.get("side"), plan.get("buy")
    if side not in ("T", "CT") or buy not in (BUYS if space else LEGACY_BUYS):
        raise ValueError("Выберите сторону и тип закупки")
    name = plan.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
        raise ValueError("Введите название длиной от 1 до 64 символов")
    slots = plan.get("slots")
    if not isinstance(slots, list) or len(slots) != 5 or not any(slots):
        raise ValueError("Назначьте хотя бы одно действие одному из пяти игроков")
    planter = None
    for slot, steps in enumerate(slots):
        if not isinstance(steps, list) or len(steps) > 96:
            raise ValueError(f"Игрок {slot + 1}: допустимо до 96 точек")
        origin = space.spawn(side,slot)[0] if space else engine._center(engine._SPAWN_CELLS[side][slot])
        grenades = []
        for index, step in enumerate(steps):
            prefix = f"Игрок {slot + 1}, точка {index + 1}"
            if not isinstance(step, dict) or step.get("kind") not in ACTIONS:
                raise ValueError(f"{prefix}: неизвестное действие")
            kind = step["kind"]
            x, y = step.get("x"), step.get("y")
            z = step.get("z")
            if space:
                if not all(type(v) in (int,float) and isfinite(v) for v in (x,y,z)):
                    raise ValueError(f"{prefix}: выберите точку на поверхности карты")
                area=space.nav.locate(space.world((x,y,z)),2)
                if area is None:
                    raise ValueError(f"{prefix}: отсутствует поверхность NAV на выбранной высоте")
            elif (
                type(x) is not int
                or type(y) is not int
                or engine._cell(x, y) not in engine._FLOOR_SET
            ):
                raise ValueError(f"{prefix}: стена или граница карты")
            if not space and (x, y) != engine._center(engine._cell(x, y)):
                raise ValueError(f"{prefix}: выберите центр клетки")
            fields = {"kind", "x", "y","z"} if space else {"kind", "x", "y"}
            if kind in ("wait", "hold", "face"):
                fields.add("seconds")
                if (
                    type(step.get("seconds")) is not int
                    or not 1 <= step["seconds"] <= 30
                ):
                    raise ValueError(f"{prefix}: длительность от 1 до 30 секунд")
            if kind == "throw":
                fields.add("utility")
                item = step.get("utility")
                if item not in tuple(UTILITY):
                    raise ValueError(f"{prefix}: неизвестная граната")
                grenades.append(item)
                if (
                    buy == "Эко"
                    or len(grenades) > (4 if space and plan["format"]==2 else 2)
                    or (space and plan["format"]==2 and grenades.count(item) > (2 if item == "Свет" else 1))
                    or (buy == BUYS[0] and sum(PRICES[g] for g in grenades) > 800)
                ):
                    raise ValueError(
                        f"{prefix}: граната недоступна при этой закупке"
                    )
                if not space and not engine.clear_line(*origin, x, y):
                    raise ValueError(f"{prefix}: стена на линии броска")
            if kind == "plant":
                if side != "T" or not (space.site_at((x,y,z)) if space else zone_at(x, y)) or planter not in (None, slot):
                    raise ValueError(
                        f"{prefix}: установку назначают одному игроку T на площадке A или B"
                    )
                planter = slot
            if set(step) != fields:
                raise ValueError(f"{prefix}: лишний параметр действия")
            if kind in MOVES:
                if space:
                    if space.path(space.locate(origin),tuple(origin),area,(x,y,z),frozenset()) is None:
                        raise ValueError(f"{prefix}: нет пути по NAV с предыдущей позиции")
                    origin=(x,y,z)
                else:
                    engine.route(engine._cell(*origin), engine._cell(x, y))
                    origin = (x, y)
    fields = ("format", "map", "geometry", "side", "buy", "name", "slots")
    return {key: plan[key] for key in fields} | {"name": name.strip()}


def step(kind, xy, **params):
    return dict(kind=kind, **dict(zip(("x","y","z"),xy)), **params)


def propose(side, buy, seed, site=None, map_id="depo"):
    if side not in ("T", "CT") or buy not in BUYS:
        raise ValueError("Выберите сторону и тип закупки")
    rng = Random(seed)
    site = site or rng.choice(("A", "B"))
    if map_id!="depo":
        space=cs2_maps.get(map_id)
        squad=[]
        for i in range(5):
            pos,_,area=space.spawn(side,i)
            squad.append(dict(zip(("x","y","z"),pos),slot=i,navArea=area))
        orders=space.orders(side,site,squad,rng.randrange(2))
        slots=[]
        for i,order in enumerate(orders["slots"]):
            steps=[step("move",point) for point in order["via"]]
            if side=="T" and i==2:
                steps.append(step("plant",order["plant"]))
            else:
                steps.append(step("hold",order["hold"],seconds=rng.randrange(2,6)))
            slots.append(steps)
        return validate(dict(format=2,map=map_id,geometry=cs2_maps.BUILD,side=side,buy=buy,
                             name=("Выход " if side=="T" else "Контроль ")+site,slots=slots))
    slots = []
    for i in range(5):
        anchor = site if side == "T" or i < 3 else ("A" if site == "B" else "B")
        stage = STAGING[anchor][rng.randrange(5)]
        hold = POSITIONS[anchor][i]
        steps = [
            step("move", APPROACH[anchor][rng.randrange(5)]),
            step("wait", stage, seconds=rng.randint(1, 3)),
        ]
        if i == 4 and buy != "Эко":
            target = rng.choice(engine._NEIGHBORS[engine._cell(*stage)])
            steps.append(step("throw", engine._center(target), utility="Дым"))
        steps.append(
            step(
                "exit" if side == "T" else "hold",
                hold,
                **({} if side == "T" else {"seconds": rng.randint(4, 9)}),
            )
        )
        if i == 2 and side == "T":
            steps.append(step("plant", POSITIONS[anchor][0]))
        slots.append(steps)
    return validate(
        dict(
            format=1,
            map=MAP["id"],
            geometry=MAP["version"],
            side=side,
            buy=buy,
            name=("Выход" if side == "T" else "Контроль") + " " + site,
            slots=slots,
        )
    )


def standards():
    return [
        dict(
            propose(side, buy, index, site),
            id=f"std-{side}-{index}",
            revision=1,
            standard=True,
        )
        for side in ("T", "CT")
        for index, buy in enumerate(LEGACY_BUYS)
        for site in [("A", "B", "A")[index]]
    ]


def equipment(steps):
    return Counter(s["utility"] for s in steps if s["kind"] == "throw")


def reference(plan):
    return {key: plan[key] for key in ("id", "revision", "name", "side", "buy")}
