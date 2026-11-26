"""Persisted stage draws. Only admitted participants and completed fixtures resolve slots."""

from .database import require


def bracket_seeds(size):
    seeds = [0]
    while len(seeds) < size:
        edge = len(seeds) * 2 - 1
        seeds = [item for seed in seeds for item in (seed, edge - seed)]
    return seeds


def draw(format_, teams, advance=1, *, bronze=False):
    require(len(set(teams)) == len(teams) and teams, "Некорректный посев")
    stage = dict(format=format_, teams=list(teams), games=[], advance=advance, round=0)
    if format_ == "swiss":
        require(
            len(teams) == 16 and advance == 8, "Для швейцарского этапа нужны 16 команд"
        )
        swiss_round(stage)
        return stage
    if format_ == "roundRobin":
        wheel = list(teams)
        if len(wheel) % 2:
            wheel.append(None)
        for rnd in range(len(wheel) - 1):
            for a, b in zip(
                wheel[: len(wheel) // 2], reversed(wheel[len(wheel) // 2 :])
            ):
                if a and b:
                    game(stage, [a, b], rnd, "Группа")
            wheel = [wheel[0], wheel[-1], *wheel[1:-1]]
        return stage
    require(format_ in ("single", "double"), "Неизвестный формат этапа")
    size = 1 << (len(teams) - 1).bit_length()
    slots = [teams[i] if i < len(teams) else None for i in bracket_seeds(size)]
    lower = []
    rnd = 0
    while len(slots) > (
        advance // 2 if format_ == "double" and advance > 1 else advance
    ):
        if format_ == "single" and len(slots) // 2 < advance:
            needed = len(slots) - advance
            contested = slots[-needed * 2 :]
            slots = slots[: -needed * 2] + [
                ("winner", game(stage, contested[i : i + 2], rnd, "Решающий матч"))
                for i in range(0, len(contested), 2)
            ]
            break
        upper = [
            game(
                stage,
                slots[i : i + 2],
                rnd,
                "Верхняя сетка" if format_ == "double" else "Плей-офф",
            )
            for i in range(0, len(slots), 2)
        ]
        drops = [("loser", i) for i in upper]
        slots = [("winner", i) for i in upper]
        if format_ == "double":
            if lower:
                # Cross the halves on injection so an upper rematch is deferred.
                drops.reverse()
                lower = [
                    ("winner", game(stage, [a, b], rnd + 1, "Нижняя сетка"))
                    for a, b in zip(lower, drops, strict=True)
                ]
            else:
                lower = drops
            if len(lower) > 1 and not (advance > 1 and len(slots) == advance // 2):
                lower = [
                    ("winner", game(stage, lower[i : i + 2], rnd + 2, "Нижняя сетка"))
                    for i in range(0, len(lower), 2)
                ]
        elif bronze and len(drops) == 2:
            game(stage, drops, rnd + 1, "За третье место")
        rnd += 2 if format_ == "double" else 1
    if format_ == "double" and advance > 1:
        slots = slots + lower
    elif format_ == "double" and lower:
        slots = [("winner", game(stage, [slots[0], lower[0]], rnd, "Гранд-финал"))]
    stage["outputs"] = slots
    return stage


def gsl(teams, advance):
    require(1 <= len(teams) <= 4 and advance in (2, 3), "Некорректная группа GSL")
    draw = dict(format="gsl", teams=list(teams), games=[], round=0, advance=advance)
    seeds = list(teams) + [None] * (4 - len(teams))
    game(draw, [seeds[0], seeds[3]], 0, "Первый матч")
    game(draw, [seeds[1], seeds[2]], 0, "Первый матч")
    upper = game(draw, [("winner", 0), ("winner", 1)], 1, "Матч победителей")
    lower = game(draw, [("loser", 0), ("loser", 1)], 1, "Матч на вылет")
    if advance == 3:
        draw["outputs"] = [("winner", upper), ("loser", upper), ("winner", lower)]
    else:
        final = game(draw, [("loser", upper), ("winner", lower)], 2, "Решающий матч")
        draw["outputs"] = [("winner", upper), ("winner", final)]
    return draw


def game(stage, slots, rnd, label):
    index = len(stage["games"])
    stage["games"].append(dict(slots=list(slots), round=rnd, label=label))
    return index


def resolve(stage, slot):
    if isinstance(slot, (tuple, list)):
        side, index = slot
        parent = stage["games"][index]
        return (side in parent, parent.get(side))
    return True, slot


def ready(stage):
    available = []
    for i, row in enumerate(stage["games"]):
        if "winner" in row or "fixture" in row:
            continue
        resolved = [resolve(stage, s) for s in row["slots"]]
        if not all(done for done, _ in resolved):
            continue
        teams = [t for _, t in resolved if t]
        if len(teams) < 2:
            row.update(winner=next(iter(teams), None), loser=None, bye=True)
        else:
            available.append((i, teams))
    return available


def table(stage):
    records = {t: dict(team=t, wins=0, losses=0, opponents=[]) for t in stage["teams"]}
    for g in stage["games"]:
        a, b = g.get("winner"), g.get("loser")
        if a and b:
            records[a]["wins"] += 1
            records[b]["losses"] += 1
            records[a]["opponents"].append(b)
            records[b]["opponents"].append(a)
    for row in records.values():
        row["buchholz"] = sum(
            records[o]["wins"] - records[o]["losses"] for o in row["opponents"]
        )
    return sorted(
        records.values(),
        key=lambda row: (-row["wins"], row["losses"], -row["buchholz"]),
    )


def swiss_round(stage):
    standings = table(stage)
    stage["round"] += 1
    pools = {}
    for row in standings:
        if max(row["wins"], row["losses"]) < 3:
            pools.setdefault((row["wins"], row["losses"]), []).append(row)
    for (wins, losses), pool in pools.items():

        def pair(rows):
            if not rows:
                return []
            first = rows[0]
            # First round pairs upper and lower seed halves. Later rounds
            # prefer the lowest remaining seed, backtracking to prevent repeats.
            for j in range(len(rows) - 1, 0, -1):
                if rows[j]["team"] in first["opponents"]:
                    continue
                tail = pair(rows[1:j] + rows[j + 1 :])
                if tail is not None:
                    return [[first["team"], rows[j]["team"]], *tail]
            return None

        if stage["round"] == 1:
            n = len(pool) // 2
            pairs = [
                [a["team"], b["team"]] for a, b in zip(pool[:n], pool[n:], strict=True)
            ]
        elif len(pool) == 6 and stage["round"] >= 4:
            priorities = (
                "162534",
                "162435",
                "152634",
                "152436",
                "142635",
                "142536",
                "162345",
                "152346",
                "132645",
                "132546",
                "142356",
                "132456",
                "123645",
                "123546",
                "123456",
            )
            pairs = None
            for layout in priorities:
                candidates = [
                    (pool[int(a) - 1], pool[int(b) - 1])
                    for a, b in zip(layout[::2], layout[1::2], strict=True)
                ]
                if all(b["team"] not in a["opponents"] for a, b in candidates):
                    pairs = [[a["team"], b["team"]] for a, b in candidates]
                    break
        else:
            pairs = pair(pool)
        require(pairs is not None, "Не удалось сформировать швейцарский раунд")
        for teams in pairs:
            i = game(
                stage,
                teams,
                stage["round"] - 1,
                f"Раунд {stage['round']} · {wins}–{losses}",
            )
            stage["games"][i]["deciding"] = max(wins, losses) == 2


def finish_round(stage):
    if any("winner" not in g for g in stage["games"]):
        return None
    if stage["format"] == "swiss" and stage["round"] < 5:
        swiss_round(stage)
        return None
    if "outputs" in stage:
        return [team for slot in stage["outputs"] if (team := resolve(stage, slot)[1])]
    return [r["team"] for r in table(stage)[: stage["advance"]]]


def record(stage, index, winner, loser):
    row = stage["games"][index]
    require(
        "winner" not in row
        and winner != loser
        and {resolve(stage, s)[1] for s in row["slots"]} == {winner, loser},
        "Результат не соответствует сетке",
    )
    row.update(winner=winner, loser=loser)
