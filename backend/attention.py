"""Live manager decisions, derived from the same career and regulations as their actions."""

from datetime import date

from . import training, competitions, cs2_maps, registrations, veto


def item(kind, level, title, detail, action, due, *, event=None, key=None):
    return dict(
        id=f"{kind}/{key or (event and event['id']) or due}",
        kind=kind,
        level=level,
        title=title,
        detail=detail,
        action=action,
        due=due,
        edition=event and event["id"],
    )


def tournament_items(c, pack, world):
    today, team = c["date"], c["team"]
    editions = c.get("circuit", {}).get("editions", {})
    pairs = set()
    for e in editions.values():
        state = e["entries"].get(team)
        if not state or e["status"] not in ("registration", "playing"):
            continue
        if state in registrations.COMMITTED:
            for clash in registrations.clashes(c, e, team):
                pair = tuple(sorted((e["id"], clash["id"])))
                if pair not in pairs:
                    pairs.add(pair)
                    yield item(
                        "conflict",
                        "required",
                        "Выберите приоритетный турнир",
                        e["title"] + " и " + clash["title"],
                        "calendar",
                        clash["dates"][0],
                        event=e,
                        key="/".join(pair),
                    )
        if e["status"] != "registration" or today < e["opens"] or today >= e["lock"]:
            continue
        if state in ("invited", "offered"):
            deadline = e.get("replyBy", {}).get(team) or e.get("applyBy") or e["lock"]
            yield item(
                "invitation",
                "required",
                "Ответьте на приглашение",
                e["title"],
                "entry",
                deadline,
                event=e,
            )
        elif state in registrations.COMMITTED:
            if not e["registrations"].get(team):
                yield item(
                    "roster",
                    "required",
                    "Зарегистрируйте пятёрку",
                    e["title"],
                    "entry",
                    e.get("applyBy", e["lock"]),
                    event=e,
                )
            elif (date.fromisoformat(e["lock"]) - date.fromisoformat(today)).days <= 2:
                yield item(
                    "lock",
                    "warning",
                    "Приближается фиксация состава",
                    e["title"],
                    "entry",
                    e["lock"],
                    event=e,
                )


def autonomous_fixture(c, fixture, pack):
    if "edition" not in fixture:
        return False
    for other in competitions.fixture_conflicts(c, fixture):
        if (set(fixture["teams"]) & set(other["teams"])) - {c["team"]}:
            return True
    missing = competitions.missing_players(c, fixture, pack)
    return bool(missing and c["team"] not in missing)


def fixture_items(c, pack, world):
    if not c["queue"]:
        return
    fixture = c["queue"][0]
    if fixture["kind"] != "match" or (fixture.get("pcw") and (not fixture["watch"] or training.unavailable(c, fixture))):
        return
    edition = c.get("circuit", {}).get("editions", {}).get(fixture.get("edition"))
    if fixture["date"] > c["date"]:
        return
    own = c["team"] in fixture["teams"]
    if not own and fixture["id"] != c.get("watchFixture"):
        return
    pool = (
        (edition["rules"] if edition else c.get("seriesProfile", veto.REGULATION))[
            "pool"
        ]
        if fixture.get("bestOf")
        else [fixture["mapId"]]
        if fixture.get("mapId") not in (None, "depo")
        else []
    )
    missing = set(pool) - set(cs2_maps.installed()) if pool else set()
    if missing:
        yield item(
            "resources",
            "warning",
            "Восстановите ресурсы карт",
            "Для наблюдения за матчем нужны " + ", ".join(sorted(missing)),
            "repair",
            c["date"],
        )
    if edition and own and c["team"] in competitions.missing_players(c, fixture, pack):
        yield item(
            "replace",
            "required",
            "Недоступен игрок стартовой пятёрки",
            edition["title"] + " · подайте экстренную замену или оформите снятие.",
            "entry",
            fixture["date"],
            event=edition,
        )
    elif not autonomous_fixture(c, fixture, pack):
        yield item(
            "match",
            "required",
            "Запланирован просмотр пракка" if fixture.get("pcw") else "Вас ждут в матч-центре",
            fixture.get("title", c["club"]),
            "play",
            fixture["date"],
            event=edition,
        )


def notices(c, pack, world):
    last = next(reversed(c.get("training", {}).get("days", {})), None)
    if last:
        yield item("training", "info", "Отчёт о подготовке", "Занятия и нагрузка игроков за " + last, "training", last)
    for msg in c["milestones"][-20:]:
        if msg["date"] == c["date"]:
            event = c.get("circuit", {}).get("editions", {}).get(msg.get("edition"))
            yield item(
                "notice",
                "info",
                msg["title"],
                msg.get("body") or c["club"],
                "overview" if event else "inbox",
                msg["date"],
                event=event,
                key=msg.get("id") or msg["title"],
            )


PROVIDERS = (tournament_items, fixture_items, notices)


def collect(c, pack, world, *, notifications=True):
    if world.get("version", 1) != 1:
        stage = world.get("series", {}).get("stage")
        title = "Предстоит Map Veto" if stage == "veto" else "Вернитесь в матч-центр"
        return [item("series", "required", title, c["club"], "match", c["date"])]
    rows = [
        row
        for source in PROVIDERS
        if notifications or source is not notices
        for row in source(c, pack, world)
    ]
    if c.get("error") and not any(r["level"] == "required" for r in rows):
        rows.append(
            item(
                "simulation",
                "required",
                "Расчёт календаря остановлен",
                c["error"],
                "retry",
                c["date"],
            )
        )
    if any(r["level"] == "required" and r["action"] != "play" for r in rows):
        rows = [r for r in rows if r["action"] != "play"]
    order = {"required": 0, "warning": 1, "info": 2}
    return sorted(rows, key=lambda r: (order[r["level"]], r["due"]))


def blockers(c, pack, world):
    return [
        r
        for r in collect(c, pack, world, notifications=False)
        if r["level"] == "required"
    ]
