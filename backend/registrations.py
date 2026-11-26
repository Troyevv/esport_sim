"""Roster versions and current employment have independent lifetimes."""

from .database import require


def conflicts(a, b):
    return a["start"] <= b["end"] and b["start"] <= a["end"]


COMMITTED = {"accepted", "locked", "qualified", "confirmed", "offered"}


def conflict_for(c, event, team):
    for other in c["circuit"]["editions"].values():
        if (
            other is not event
            and other["entries"].get(team) in COMMITTED
            and conflicts(event, other)
        ):
            return other
    return None


def player_conflict(c, event, team, players, reserves=()):
    starters = set(players)
    full_roster = starters.union(reserves)
    for other in c["circuit"]["editions"].values():
        if not conflicts(event, other):
            continue
        for tid, rows in other["registrations"].items():
            if tid != team and rows and other["entries"].get(tid) in COMMITTED:
                last = rows[-1]
                if other is event:
                    clash = full_roster.intersection(last["players"] + last["reserves"])
                else:
                    # An academy starter can also be the senior team’s unfielded reserve.
                    # Activating that reserve runs this check again for the new five.
                    clash = starters.intersection(last["players"])
                if clash:
                    return other
    return None


def signup(c, event, team, pack):
    require(
        event["opens"] <= c["date"] < event.get("applyBy", event["lock"]),
        "Регистрация закрыта",
    )
    require(
        event["admission"] in ("open", "rankedOpen", "firstCome")
        or event["entries"].get(team) == "invited",
        "Нет приглашения или места из квалификации",
    )
    require(in_region(c, event, team, pack), "Регион не соответствует регламенту")
    require(
        event["entries"].get(team) in (None, "invited", "declined"),
        "Вы уже подтвердили участие",
    )
    if event.get("singleOrganization"):
        organization = pack["teams"][team]["organization"]
        require(
            not organization
            or all(
                t == team
                or pack["teams"][t]["organization"] != organization
                or st not in COMMITTED
                for t, st in event["entries"].items()
            ),
            "В турнире уже участвует состав этой организации",
        )
    parent = event
    while parent.get("feeds"):
        parent = c["circuit"]["editions"][parent["feeds"]]
        require(
            parent["entries"].get(team)
            not in ("invited", "accepted", "locked", "qualified"),
            "Команда уже получила место в следующем этапе",
        )
    clash = conflict_for(c, event, team)
    if clash:
        raise ValueError("Пересечение дат: " + clash["title"])
    require(
        sum(s == "accepted" for s in event["entries"].values()) < event["capacity"]
        or event["admission"] == "rankedOpen",
        "Все места заняты",
    )
    event["entries"][team] = "accepted"


def available(c, team, pack):
    main = pack["rosters"][c["teams"][team]]["players"]
    bench = c["circuit"]["bench"].get(team, [])
    return list(dict.fromkeys([*main, *bench]))


def submit(c, event, team, pack, players, reserves, coach, *, reason=None):
    require(
        event["entries"].get(team)
        in ("accepted", "locked", "qualified", "confirmed", "offered"),
        "Участие не подтверждено",
    )
    require(
        isinstance(players, list)
        and len(players) == 5
        and isinstance(reserves, list)
        and len(reserves) <= event["rules"]["reserves"],
        "Требуется пятёрка и допустимое число запасных",
    )
    all_ids = players + reserves
    require(
        all(isinstance(p, str) for p in all_ids) and len(set(all_ids)) == len(all_ids),
        "Игрок повторяется в заявке",
    )
    allowed = available(c, team, pack)
    versions = event["registrations"].get(team, [])
    if reason is None:
        require(event["opens"] <= c["date"] < event["lock"], "Наступил Roster Lock")
        if event.get("applyBy", "9999") <= c["date"]:
            require(
                event["entries"].get(team) in ("confirmed", "offered"),
                "Заявки уже отобраны",
            )
        require(set(all_ids) <= set(allowed), "В заявке есть недоступный игрок")
    else:
        require(
            event["lock"] <= c["date"] <= event["end"]
            and event["status"] == "playing"
            and versions
            and isinstance(reason, str)
            and 0 < len(reason.strip()) <= 240,
            "Укажите основание замены после фиксации",
        )
        old = versions[-1]
        incoming = set(players) - set(old["players"])
        outgoing = set(old["players"]) - set(players)
        require(
            len(incoming) == len(outgoing) == 1
            and incoming <= set(old["reserves"])
            and set(players) <= set(allowed)
            and set(all_ids) == set(old["players"] + old["reserves"])
            and coach == old["coach"],
            "После фиксации возможна только замена на зарегистрированного запасного",
        )
    require(
        coach is None
        or isinstance(coach, str)
        and pack["staff"].get(coach, {}).get("team") == team,
        "Тренер не принадлежит команде",
    )
    core = event.get("invites", {}).get(team)
    if core:
        minimum = 3 if reason else event["rules"]["core"]
        require(
            len(set(players) & set(core)) >= minimum, "Не сохранено приглашённое ядро"
        )
    if event["admission"] == "invitation" and reserves:
        from . import vrs

        countries = vrs.country_regions()

        def region(five):
            return vrs.plurality(
                [countries.get(vrs.nationality(pack, p)) for p in five]
            )

        reference = region(core or players)
        require(
            region(players) == reference
            and all(
                region([r if p == out else p for p in players]) == reference
                for r in reserves
                for out in players
            ),
            "Замена меняет регион состава",
        )
    require(
        not player_conflict(c, event, team, players, reserves),
        "Игрок заявлен за другую команду",
    )
    row = dict(
        version=len(versions) + 1,
        date=c["date"],
        players=list(players),
        reserves=list(reserves),
        coach=coach,
        reason=reason,
    )
    event["registrations"].setdefault(team, []).append(row)
    return row


INVITATIONAL = {
    "invitation",
    "regionalInvite",
    "finalsInvite",
    "leagueInvite",
    "closedInvite",
    "mixedInvite",
    "globalInvite",
}


def in_region(c, event, team, pack):
    region = event["region"]
    declared = pack["teams"][team]["region"]
    from . import vrs

    countries = [
        vrs.nationality(pack, p) for p in pack["rosters"][c["teams"][team]]["players"]
    ]
    classified = vrs.plurality(
        [vrs.country_regions().get(country) for country in countries if country]
    )
    if (
        region != "Global"
        and (declared or (classified if any(countries) else None)) != region
    ):
        return False
    sub = event.get("subregion")
    sa = {
        "AR",
        "BO",
        "BR",
        "CL",
        "CO",
        "EC",
        "FK",
        "GF",
        "GY",
        "PY",
        "PE",
        "SR",
        "UY",
        "VE",
    }
    oc = {"AU", "NZ", "FJ", "PG", "GU", "NC", "WS", "TO", "PF", "VU", "SB"}
    if sub in ("South America", "North America"):
        a = sum(p in sa for p in countries)
        b = sum(
            vrs.country_regions().get(p) == "Americas" and p not in sa
            for p in countries
        )
        return (a > b if sub == "South America" else b >= a) and max(a, b) > 0
    if sub in ("Asia", "Oceania"):
        a = sum(p in oc for p in countries)
        b = sum(
            vrs.country_regions().get(p) == "Asia" and p not in oc for p in countries
        )
        return (a > b if sub == "Oceania" else b >= a) and max(a, b) > 0
    return True
