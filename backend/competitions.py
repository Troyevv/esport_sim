"""Competition calendar, registration and stage advancement inside the career transaction."""

import hashlib
from calendar import monthrange
from copy import deepcopy
from collections import Counter, defaultdict

from . import competition_stages as stages, registrations, vrs
from .competition_catalog import offset, season, seed_data
from .competition_catalog import cct_europe
from . import competition_scene, staff
from .database import day, require


def clock(c, date, title, event=None):
    review = next(
        (e for e in c["queue"] if e["date"] == date and e["kind"] == "review"), None
    )
    if review is None:
        review = dict(kind="review", id="day-" + date, date=date, teams=[], title=title)
        c["queue"].append(review)
    if event:
        item = dict(edition=event["id"], tournament=event["title"], title=title)
        agenda = review.setdefault("agenda", [])
        if item not in agenda:
            agenda.append(item)


def order(c):
    c["queue"].sort(
        key=lambda e: (
            e["date"],
            e["kind"] == "match",
            c["team"] in e["teams"],
            e["id"],
        )
    )


def notice(c, event, title, body):
    identity = hashlib.sha256(
        "\0".join((event["id"], c["date"], title, body)).encode()
    ).hexdigest()[:24]
    if any(
        m.get("id") == identity
        for m in reversed(c["milestones"])
        if m["date"] == c["date"]
    ):
        return
    c["milestones"].append(
        dict(
            date=c["date"],
            id=identity,
            edition=event["id"],
            sender=event["organizer"],
            title=event["title"] + " · " + title,
            body=body,
            matches=None,
        )
    )


def snapshot(c, date):
    dates = {**seed_data()["snapshots"], **c["circuit"]["snapshots"]}
    key = max((key for key in dates if key <= date), default=None)
    return (key, dates[key]) if key else (None, [])


def rank(c, date, pack):
    key, rows = snapshot(c, date)
    by_player = defaultdict(list)
    for team, rid in c["teams"].items():
        for pid in pack["rosters"][rid]["players"]:
            by_player[pid].append(team)
    matched = {}
    for row in rows:
        overlap = Counter(t for pid in row.get("core", []) for t in by_player[pid])
        clubs = [t for t, n in overlap.items() if n >= 3]
        team = (
            row.get("team")
            if row.get("team") in clubs
            else clubs[0]
            if len(clubs) == 1
            else None
        )
        if team and team not in matched:
            matched[team] = row
    return key, matched


def init(c, pack):
    c["clubNames"] = {t: pack["teams"][t]["name"] for t in c["teams"]}
    c["circuit"] = dict(
        version=1,
        model=vrs.MODEL,
        historyEdition="liquipedia-20261125-v1",
        editions={},
        bench={},
        snapshots={},
        awards={},
    )
    for row in seed_data()["major"]:
        tid = row["team"]
        if tid in c["teams"]:
            main = pack["rosters"][c["teams"][tid]]["players"]
            c["circuit"]["bench"][tid] = [
                p for p in row["players"] + row["reserves"] if p not in main
            ]
    publish(c, pack)
    add_season(c, pack, int(c["date"][:4]))


def add_season(c, pack, year):
    events = c["circuit"]["editions"]
    calendar = season(year)
    if "tournamentSupplement" in pack:
        calendar += cct_europe(year)
    if year == 2026:
        calendar += [e for e in season(2027) if not e["simulated"]]
    for event in calendar:
        if event["id"] in events:
            continue
        events[event["id"]] = event
        if event["id"] == "pgl-major-2026":
            import_major(c, event, pack)
        elif year == 2026 and event["series"] in ("cct-europe", "cct-europe-playin"):
            import_cct(c, event, pack)
        for key, title in (
            ("opens", "Открытие регистрации"),
            ("lock", "Фиксация составов"),
            ("start", "Старт турнира"),
        ):
            if event[key] > c["date"]:
                clock(c, event[key], title, event)
        if "applyBy" in event:
            for n in (0, 1, 2):
                date = offset(event["applyBy"], n)
                if date > c["date"]:
                    clock(c, date, "Подтверждение заявки", event)
        if event["admission"] == "invitation" and event["lock"] > c["date"]:
            clock(c, offset(event["lock"], -3), "Оставшиеся региональные места Major")
        reminder = offset(event["lock"], -1)
        if reminder > c["date"]:
            clock(c, reminder, "Завтра завершается регистрация", event)
    process_day(c, pack)
    clock(c, f"{year + 1}-01-01", "Новый сезон")
    for month in range(1, 13):
        first = f"{year}-{month:02}-01"
        publication = offset(first, (-day(first).weekday()) % 7)
        if publication > c["date"]:
            clock(c, publication, "Публикация VRS")
    order(c)


def import_cct(c, event, pack):
    qualifier = event["series"] == "cct-europe-playin"
    rows = competition_scene.lineups()
    rows = rows[:16] if qualifier else rows[16:]
    event.update(snapshot="2026-10-05", invites={}, inviteRegions={}, announced=True)
    field = []
    for row in rows:
        team = row["id"]
        players = [p["id"] for p in row["players"]]
        coach = staff.registered_coach(c, pack, team)
        event["entries"][team] = "locked" if qualifier else "accepted"
        event["registrations"][team] = [
            dict(
                version=1,
                date=c["date"],
                reason=None,
                players=players,
                reserves=[],
                coach=coach,
            )
        ]
        event["invites"][team] = players.copy()
        event["inviteRegions"][team] = "Europe"
        field.append(team)
    if qualifier:
        event["status"] = "playing"
        event["stages"][0]["groupSeeds"] = [
            list(range(i, i + 4)) for i in range(0, 16, 4)
        ]
        begin(c, event, field)
    else:
        event["direct"] = {"0": field[:12], "1": field[12:]}


def import_major(c, event, pack):
    rows = seed_data()["major"]
    event["invites"] = {}
    for row in rows:
        tid = row["team"]
        require(tid in c["teams"], "В базе отсутствует участник Singapore Major")
        event["entries"][tid] = "locked"
        event["invites"][tid] = row["players"].copy()
        event["registrations"][tid] = [
            dict(
                version=1,
                date=event["lock"],
                reason=None,
                players=row["players"].copy(),
                reserves=row["reserves"].copy(),
                coach=row["coach"],
            )
        ]
    ids = [r["team"] for r in rows]
    event["direct"] = {"0": ids[16:], "1": ids[8:16], "2": ids[:8]}
    event.update(status="playing", snapshot="2026-11-02")
    event["inviteRegions"] = {
        r["team"]: r["region"]
        for r in seed_data()["snapshots"]["2026-11-02"]
        if r.get("team")
    }
    for row in rows:
        event["inviteRegions"].setdefault(
            row["team"],
            vrs.plurality(
                [
                    vrs.country_regions().get(vrs.nationality(pack, p))
                    for p in row["players"]
                ]
            ),
        )
    opening = ids[16:20] + [ids[22], ids[20], ids[21]] + ids[23:]
    event["direct"]["0"] = opening
    draw = stages.draw("swiss", opening, 8)
    draw["games"].clear()
    # Series results on 24 November, before the shipped edition starts.
    # Values refer to the published 32-team participant manifest, winning team first.
    rounds = [
        [
            (26, 18, 6),
            (31, 23, 11),
            (16, 24, 10),
            (22, 28, 1),
            (17, 25, 3),
            (27, 19, 9),
            (29, 20, 7),
            (21, 30, 6),
        ],
        [
            (26, 21, 11),
            (22, 27, 8),
            (29, 17, 9),
            (16, 31, 10),
            (20, 25, 8),
            (18, 30, 3),
            (24, 23, 8),
            (19, 28, 3),
        ],
    ]
    for rnd, matches in enumerate(rounds):
        for winner, loser, score in matches:
            teams = [ids[winner], ids[loser]]
            i = stages.game(draw, teams, rnd, f"Раунд {rnd + 1}")
            draw["games"][i].update(
                winner=teams[0],
                loser=teams[1],
                historical=True,
                score=[13, score],
                date="2026-11-24",
            )
    draw["round"] = 2
    stages.swiss_round(draw)
    event["draws"] = [[draw]]
    schedule_draw(c, event)


def selected(c, event, pack):
    return [t for t in c["teams"] if registrations.in_region(c, event, t, pack)]


def wildcard_pool(c, event, stamp, ranked, ranks, pack):
    date = day(stamp)
    month = (date.month + 5) % 12 + 1
    year = date.year - int(date.month <= 6)
    since = date.replace(
        year=year, month=month, day=min(date.day, monthrange(year, month)[1])
    ).isoformat()
    former = set()
    for date, rows in {**seed_data()["snapshots"], **c["circuit"]["snapshots"]}.items():
        if since <= date <= stamp:
            for r in rows:
                if r["rank"] <= 12:
                    former.update(r["core"])
    finalists = []
    for e in c["circuit"]["editions"].values():
        if (
            e["status"] == "finished"
            and since <= e["end"] <= stamp
            and e["prestige"] >= event["prestige"]
            and not e.get("feeds")
        ):
            for t in e["placements"][:2]:
                finalists.append(set(e["registrations"][t][-1]["players"]))
    candidates = []
    for t in ranked:
        members = set(pack["rosters"][c["teams"][t]]["players"])
        if ranks[t]["rank"] > 12 and (
            len(members & former) >= 3
            or any(len(members & five) >= 3 for five in finalists)
        ):
            candidates.append(t)
    return candidates


def issue_invites(c, event, pack):
    stamp, ranks = rank(c, min(event["opens"], c["date"]), pack)
    event["snapshot"] = stamp
    eligible = selected(c, event, pack)
    ranked = sorted((t for t in eligible if t in ranks), key=lambda t: ranks[t]["rank"])
    if "minRegional" in event:
        ranked = [t for t in ranked if ranks[t]["regional"] >= event["minRegional"]]
    admission = event["admission"]
    previous = list(c["circuit"]["editions"].values())
    preferred = []
    if admission == "invitation":
        regions = ("Europe", "Americas", "Asia")
        slots = [(6, 6, 4), (6, 1, 1), (6, 2, 0)]
        last = max(
            (
                e
                for e in previous
                if e["admission"] == "invitation" and e["status"] == "finished"
            ),
            key=lambda e: e["end"],
            default=None,
        )
        if last:
            for stage, field in [
                (1, last["placements"][8:16]),
                (2, last["placements"][:8]),
            ]:
                slots[stage] = tuple(
                    sum(last["inviteRegions"].get(t) == r for t in field)
                    for r in regions
                )
        for stage in (2, 1, 0):
            for region, count in zip(regions, slots[stage], strict=True):
                preferred.append(
                    (
                        stage,
                        count,
                        [
                            t
                            for t in ranked
                            if ranks[t]["region"] == region
                            and set(ranks[t]["core"])
                            == set(pack["rosters"][c["teams"][t]]["players"])
                            and region_stable(c, ranks[t], stamp)
                        ],
                    )
                )
    elif admission == "regionalInvite":
        sub = event["subregion"]
        seeds = []
        if not event["simulated"]:
            tier = "Advanced" if sub == "North America" else "Open"
            seeds = historical_seeds(
                f"ESEA/Season_58/{tier}/" + sub.replace(" ", "_"), 2
            )
        preferred = [
            (
                0,
                event["capacity"],
                [t for t in seeds if t in eligible]
                + [t for t in ranked if ranks[t]["rank"] > 12],
            )
        ]
    elif admission == "finalsInvite":
        group = event["subregion"]
        seeds = []
        if not event["simulated"]:
            names = ["Asia", "Oceania"] if group == "Asia-Oceania" else [group]
            for name in names:
                for n in range(1, 13 if name == "Europe" else 4):
                    base = (
                        "ESL/Challenger_League/Season_52/"
                        + name.replace(" ", "_")
                        + "/Cup_"
                        + str(n)
                    )
                    picks = historical_seeds(base, 2)
                    seeds.extend(
                        next(
                            ([t] for t in picks if t in eligible and t not in seeds), []
                        )
                    )
            if group == "Europe":
                seeds.extend(historical_seeds("ESEA/Season_58/Advanced/Europe", 2))
        for e in previous:
            if e.get("finals") == event["id"] and e["status"] == "finished":
                seeds.extend(
                    next(([t] for t in e["placements"][:2] if t not in seeds), [])
                )
        preferred = [
            (
                0,
                event["capacity"],
                [t for t in seeds if t in eligible]
                + [t for t in ranked if ranks[t]["rank"] > 12],
            )
        ]
    elif admission == "mixedInvite":
        for sub in ("North America", "South America"):
            preferred.append(
                (
                    0,
                    1,
                    [
                        t
                        for t in ranked
                        if registrations.in_region(
                            c, dict(region="Americas", subregion=sub), t, pack
                        )
                    ],
                )
            )
        preferred.append((0, 11, ranked))
    elif admission == "closedInvite":
        main = c["circuit"]["editions"][event["feeds"]]
        preferred = [
            (
                0,
                event.get("inviteCount", event["capacity"]),
                [t for t in ranked if t not in main.get("invites", {})],
            )
        ]
    elif admission == "leagueInvite":
        feeders = [
            e
            for e in previous
            if e["series"] == "ecl-finals"
            and e["status"] == "finished"
            and e["year"] == event["feederYear"]
            and e["id"].endswith("-spring") == (event["half"] == "spring")
            and not e["id"].endswith("-summer")
        ]
        seeds = [e["placements"][0] for e in feeders]
        direct = event["capacity"] - 4 - event.get("wildcardCount", 0)
        preferred = [(0, 4, seeds), (0, direct, ranked)]
        if event.get("wildcardCount"):
            preferred.append(
                (0, 1, wildcard_pool(c, event, stamp, ranked, ranks, pack) + ranked)
            )
        # An unfilled league spot passes to an eligible roster on the invitation list.
        preferred[0] = (0, 4, seeds + ranked)
    elif event.get("wildcardCount"):
        n = event["wildcardCount"]
        preferred = [
            (0, event["capacity"] - n, ranked),
            (0, n, wildcard_pool(c, event, stamp, ranked, ranks, pack) + ranked),
        ]
    else:
        preferred = [
            (stage, n, ranked)
            for stage, n in event.get(
                "stageSlots", [(0, event.get("inviteCount", event["capacity"]))]
            )
        ]
    event["invitePools"] = [
        dict(stage=i, count=n, teams=list(dict.fromkeys(pool)))
        for i, n, pool in preferred
    ]
    event["inviteCores"] = {
        t: ranks[t]["core"] if t in ranks else pack["rosters"][c["teams"][t]]["players"]
        for _, _, pool in preferred
        for t in pool
    }
    event["inviteRegions"] = {t: ranks[t]["region"] for t in ranked}
    event["invites"] = {}
    refill_invites(c, event)


def historical_seeds(eid, count):
    h = vrs.history()
    places = h["events"].get(eid, {}).get("placements", {})
    return [
        tid
        for org, place in sorted(places.items(), key=lambda entry: entry[1])
        if 0 < place <= count and (tid := h["clubs"].get(org, {}).get("team"))
    ]


def region_stable(c, row, stamp):
    months = day(stamp).year * 12 + day(stamp).month
    dates = {**seed_data()["snapshots"], **c["circuit"]["snapshots"]}
    for date, rows in dates.items():
        if 0 < months - (day(date).year * 12 + day(date).month) <= 3:
            if any(
                r["region"] != row["region"]
                and len(set(row["core"]) & set(r.get("core", []))) >= 3
                for r in rows
            ):
                return False
    return True


def refill_invites(c, event):
    assigned = set()
    event["direct"] = {}
    for team, slot in event.get("qualifiedStages", {}).items():
        if event["entries"].get(team) not in ("missed", "declined"):
            event["direct"].setdefault(slot, []).append(team)
            assigned.add(team)
    for group in event["invitePools"]:
        chosen = []
        for team in group["teams"]:
            if len(chosen) == group["count"]:
                break
            if team in assigned or event["entries"].get(team) in ("declined", "missed"):
                continue
            assigned.add(team)
            chosen.append(team)
            if team not in event["invites"]:
                event["invites"][team] = event["inviteCores"][team].copy()
                event["entries"][team] = "invited"
                if team == c["team"]:
                    notice(
                        c,
                        event,
                        "Приглашение",
                        "Подтвердите участие и подайте состав до "
                        + event["lock"]
                        + ".",
                    )
        event["direct"].setdefault(str(group["stage"]), []).extend(chosen)


def process_day(c, pack):
    events = c["circuit"]["editions"]
    # Higher prestige and then larger purses get the first decision on conflicting dates.
    for event in sorted(events.values(), key=tournament_priority):
        if event["status"] != "registration" or c["date"] < event["opens"]:
            continue
        if event["admission"] == "qualified":
            if c["date"] == offset(event["lock"], -1) and event["entries"].get(
                c["team"]
            ) in ("qualified", "invited"):
                notice(c, event, "Дедлайн завтра", "Проверьте заявку основного этапа.")
            continue
        if c["date"] < event["lock"]:
            if (
                event["admission"] in registrations.INVITATIONAL
                and "invites" not in event
            ):
                issue_invites(c, event, pack)
            if not event.get("announced"):
                event["announced"] = True
                if (
                    c["team"] in selected(c, event, pack)
                    and event["admission"] not in registrations.INVITATIONAL
                ):
                    notice(
                        c,
                        event,
                        "Приглашение"
                        if event["admission"] == "invitation"
                        else "Открыта регистрация",
                        "Подтвердите участие и подайте состав до "
                        + event["lock"]
                        + ".",
                    )
            if offset(c["date"], 1) == event["lock"] and event["entries"].get(
                c["team"]
            ) in ("accepted", "qualified", "invited", "confirmed", "offered"):
                notice(
                    c, event, "Дедлайн завтра", "Проверьте пятёрку, запасных и тренера."
                )
            if event.get("applyBy", "9999") <= c["date"]:
                select_applicants(c, event, pack)
            else:
                auto_register(c, event, pack)
                if event.get("invitePools") and not event.get("inviteClosed"):
                    for _ in range(event["capacity"]):
                        refill_invites(c, event)
                        if not any(
                            t != c["team"] and v == "invited"
                            for t, v in event["entries"].items()
                        ):
                            break
                        auto_register(c, event, pack)
            if event["admission"] == "invitation" and c["date"] == offset(
                event["lock"], -3
            ):
                last_chance(c, event, pack)
        else:
            lock(c, event, pack)
    order(c)


def auto_register(c, event, pack):
    regional_ranks = (
        rank(c, c["date"], pack)[1] if event["admission"] == "rankedOpen" else {}
    )
    candidates = selected(c, event, pack)
    if event["admission"] == "firstCome":
        # Preserve published sign-up order at the career boundary. Later arrivals
        # choose a date within the remaining registration window.
        announced = [
            "PURE",
            "Monte",
            "HEROIC",
            "9INE",
            "Hype Tech",
            "B8",
            "ENVY",
            "GamerLegion",
            "WBT",
            "AIMCLUB Academy",
            "Balkan Outlaws",
            "HOTU",
            "Illyrians",
            "STATE",
            "INFINITE",
        ]
        positions = (
            {name.casefold(): i for i, name in enumerate(announced)}
            if not event["simulated"]
            else {}
        )

        def arrival(t):
            name = pack["teams"][t]["name"].casefold()
            position = next(
                (
                    i
                    for registered, i in positions.items()
                    if name in (registered, registered + " esports")
                ),
                None,
            )
            if position is not None:
                return event["opens"], position
            first = max(c["start"], event["opens"])
            window = max(1, (day(event["lock"]) - day(first)).days - 1)
            seed = int.from_bytes(
                hashlib.sha256((event["id"] + t).encode()).digest()[:4], "big"
            )
            return offset(first, 1 + seed % window), seed

        candidates = sorted(
            (t for t in candidates if arrival(t)[0] <= c["date"]), key=arrival
        )
    for team in candidates:
        if team == c["team"] or event["entries"].get(team) not in (None, "invited"):
            continue
        if (
            event["admission"] in registrations.INVITATIONAL
            and team not in event["invites"]
        ):
            continue
        if event["admission"] == "rankedOpen" and team not in regional_ranks:
            continue
        if event.get("feeds") and c["circuit"]["editions"][event["feeds"]]["entries"].get(team) in registrations.COMMITTED:
            continue
        if event["series"] == "cct-oq" and pack["teams"][team]["tier"] == 1:
            continue
        if any(
            e.get("feeds") == event.get("feeds")
            and e is not event
            and team in e.get("advanced", [])
            for e in c["circuit"]["editions"].values()
        ) and event.get("feeds"):
            continue
        try:
            collisions = registrations.clashes(c, event, team)
            others = [c["circuit"]["editions"][r["id"]] for r in collisions]
            if others and all(priority_for(event, team) < priority_for(other, team) for other in others):
                # Validate eligibility and capacity before releasing an accepted place.
                registrations.signup(c, event, team, pack, prioritise={o["id"] for o in others})
            else:
                registrations.signup(c, event, team, pack)
        except ValueError as exc:
            if event["entries"].get(team) == "invited":
                event["entries"][team] = "declined"
                event.setdefault("reasons", {})[team] = str(exc)
            continue
        players = pack["rosters"][c["teams"][team]]["players"]
        reserve = c["circuit"]["bench"].get(team, [])[: event["rules"]["reserves"]]
        if event["admission"] == "invitation":
            reference = vrs.plurality(
                [vrs.country_regions().get(vrs.nationality(pack, p)) for p in players]
            )
            reserve = [
                r
                for r in reserve
                if all(
                    vrs.plurality(
                        [
                            vrs.country_regions().get(
                                vrs.nationality(pack, r if p == out else p)
                            )
                            for p in players
                        ]
                    )
                    == reference
                    for out in players
                )
            ]
        coach = staff.registered_coach(c, pack, team)
        try:
            registrations.submit(c, event, team, pack, players, reserve, coach)
            for other in others:
                leave(c, other, team, pack, "Приоритет: " + event["title"])
        except ValueError as exc:
            event["entries"][team] = "declined"
            event.setdefault("reasons", {})[team] = str(exc)


def select_applicants(c, event, pack):
    if "waiting" not in event:
        stamp, ranks = rank(c, event["seedDate"], pack)
        event["seedSnapshot"] = stamp
        candidates = []
        for t, state in event["entries"].items():
            if state != "accepted":
                continue
            versions = event["registrations"].get(t, [])
            if not versions:
                event["entries"][t] = "missed"
            elif (
                t not in ranks
                or len(set(versions[-1]["players"]) & set(ranks[t]["core"])) < 3
            ):
                event["entries"][t] = "notSelected"
            else:
                candidates.append(t)
                event["entries"][t] = "waiting"
        event["waiting"] = sorted(candidates, key=lambda t: ranks[t]["rank"])
    for t, state in event["entries"].items():
        if state == "offered" and event["replyBy"][t] <= c["date"]:
            event["entries"][t] = "missed"
            if t == c["team"]:
                notice(
                    c,
                    event,
                    "Истёк срок подтверждения",
                    "Место передано следующей команде.",
                )
    for t in event["waiting"]:
        if (
            sum(v in ("confirmed", "offered") for v in event["entries"].values())
            >= event["capacity"]
        ):
            break
        if event["entries"][t] == "waiting":
            event["entries"][t] = "offered" if t == c["team"] else "confirmed"
            event.setdefault("replyBy", {})[t] = min(
                event["lock"], offset(c["date"], 1)
            )
            if t == c["team"]:
                notice(
                    c,
                    event,
                    "Подтвердите место",
                    "Срок подтверждения " + event["replyBy"][t] + ".",
                )


def lock(c, event, pack):
    eligible = []
    for team, state in event["entries"].items():
        if state == "waiting":
            event["entries"][team] = "notSelected"
            continue
        if state not in ("accepted", "invited", "qualified", "confirmed", "offered"):
            continue
        versions = event["registrations"].get(team)
        if (
            state in ("offered", "invited")
            or not versions
            or not set(versions[-1]["players"] + versions[-1]["reserves"])
            <= set(registrations.available(c, team, pack))
        ):
            event["entries"][team] = "missed"
            if team == c["team"]:
                notice(
                    c,
                    event,
                    "Пропущена регистрация",
                    "На момент фиксации нет допустимой пятёрки.",
                )
        else:
            eligible.append(team)
    stamp, ranks = rank(c, event.get("seedDate", c["date"]), pack)
    event["seedSnapshot"] = stamp
    eligible.sort(key=lambda t: (ranks[t]["rank"] if t in ranks else 10**6, t))
    # Open CCT slots are limited at signup; ECL selects ranked applications at lock.
    if event["admission"] == "rankedOpen":
        eligible = [t for t in eligible if t in ranks]
    eligible = eligible[: event["capacity"]]
    if "poolBySize" in event:
        total = max(
            (amount for size, amount in event["poolBySize"] if size <= len(eligible)),
            default=0,
        )
        event["prizes"] = [total * share // 100 for share in event["shares"]]
    field = set(eligible)
    for team, status in event["entries"].items():
        if status in ("accepted", "qualified", "confirmed"):
            event["entries"][team] = "locked" if team in field else "notSelected"
    if event["admission"] == "invitation" or event.get("stageSlots"):
        for key, teams in event["direct"].items():
            event["direct"][key] = sorted(
                (t for t in teams if t in field),
                key=lambda t: ranks[t]["rank"] if t in ranks else 10**6,
            )
        eligible = event["direct"]["0"]
    if event["admission"] == "invitation" and any(
        len(event["direct"].get(str(i), [])) != n for i, n in enumerate([16, 8, 8])
    ):
        event.update(
            status="cancelled", reason="Не заполнены места по региональным квотам Major"
        )
        return
    if "groupSeeds" in event["stages"][0] and len(eligible) != sum(
        map(len, event["stages"][0]["groupSeeds"])
    ):
        event.update(status="cancelled", reason="Не заполнены приглашения для групп")
        return
    if (
        len(eligible) < event.get("minTeams", 2)
        or event["stages"][0]["format"] == "swiss"
        and len(eligible) != 16
    ):
        event.update(status="cancelled", reason="Недостаточно допущенных команд")
        return
    event["status"] = "playing"
    if c["team"] in field:
        notice(
            c,
            event,
            "Состав зафиксирован",
            "Дальнейшие замены допускаются по регламенту.",
        )
    begin(c, event, eligible)


def begin(c, event, field):
    spec = event["stages"][len(event["draws"])]
    if (
        not field
        or spec["format"] == "swiss"
        and len(field) != 16
        or "fromGroups" in spec
        and len(field) < len(spec["fromGroups"])
    ):
        event.update(
            status="cancelled",
            reason="После снятия участников не хватает допущенных составов для следующего этапа",
        )
        return
    if spec["format"] == "roundRobin" and "groupSize" in spec:
        groups = (len(field) + spec["groupSize"] - 1) // spec["groupSize"]
        draws = [stages.draw("roundRobin", field[i::groups], 2) for i in range(groups)]
        for draw in draws:
            draw["secondPlaceBO"] = spec["secondPlaceBO"]
    elif spec["format"] == "doubleGroups":
        draws = [stages.draw("double", field[i::2], advance=4) for i in range(2)]
    elif spec["format"] == "gsl":
        count = spec.get("groups", 4)
        groups = (
            [[field[i] for i in indices] for indices in spec["groupSeeds"]]
            if "groupSeeds" in spec
            else [field[i::count] for i in range(count)]
        )
        draws = [
            stages.gsl(group, spec["advance"] // count) for group in groups if group
        ]
    else:
        draws = [
            stages.draw(
                spec["format"], field, spec["advance"], bronze=spec.get("bronze", False)
            )
        ]
    for draw in draws:
        withdrawn = [t for t in draw["teams"] if event["entries"].get(t) == "withdrawn"]
        if withdrawn:
            draw["withdrawn"] = withdrawn
    event["draws"].append(draws)
    if c["team"] in field:
        notice(c, event, "Опубликована сетка", spec["name"])
    schedule_draw(c, event)


def schedule_draw(c, event):
    index = len(event["draws"]) - 1
    spec = event["stages"][index]
    draws = event["draws"][index]
    promoted = []
    for group, draw in enumerate(draws):
        ready = stages.ready(draw)
        output = stages.finish_round(draw)
        if output is not None:
            promoted.extend(output)
        elif not ready:
            ready = stages.ready(draw)
        # Future opponent slots can resolve days after a team withdrew. Settle
        # those matches before emitting fixtures or advancing another round.
        while any(any(event["entries"].get(t) == "withdrawn" for t in teams) for _,teams in ready):
            for n, teams in ready:
                absent = [t for t in teams if event["entries"].get(t) == "withdrawn"]
                if absent:
                    row = draw["games"][n]
                    row.update(winner=next((t for t in teams if t not in absent), None),
                               loser=absent[0] if len(absent)==1 else None,
                               administrative=True, reason="Снятие команды")
            ready = stages.ready(draw)
            output = stages.finish_round(draw)
            if output is not None:
                promoted.extend(output)
            elif not ready:
                ready = stages.ready(draw)
        for n, teams in ready:
            row = draw["games"][n]
            fixture = f"{event['id']}.{index}.{group}.{n}"
            duration = (day(spec["end"]) - day(spec["start"])).days
            max_round = max(g["round"] for g in draw["games"])
            delta = (
                spec["roundDays"][row["round"]]
                if "roundDays" in spec
                else round(duration * row["round"] / max(1, max_round))
            )
            if "groupDays" in spec:
                delta = spec["groupDays"][group][row["round"]]
            when = max(c["date"], offset(spec["start"], delta))
            best = row.get("bestOf", 3 if row.get("deciding") else spec["bestOf"])
            if draw.get("outputs") == [("winner", n)] or draw.get("outputs") == [
                ["winner", n]
            ]:
                best = spec.get("finalBO", best)
            row.update(fixture=fixture, date=when)
            if c["team"] in teams:
                rival = next(t for t in teams if t != c["team"])
                notice(
                    c,
                    event,
                    "Предстоящий соперник",
                    f"{when} · BO{best} · " + c.get("clubNames", {}).get(rival, rival),
                )
            c["queue"].append(
                dict(
                    kind="match",
                    id=fixture,
                    date=when,
                    teams=teams,
                    edition=event["id"],
                    title=event["title"],
                    stage=index,
                    group=group,
                    game=n,
                    bestOf=best,
                    seed=int.from_bytes(
                        hashlib.sha256(fixture.encode()).digest()[:4], "big"
                    )
                    >> 1,
                )
            )
    resolve_slots(c)
    if any(any("winner" not in g for g in draw["games"]) for draw in draws):
        return
    if index + 1 < len(event["stages"]):
        next_spec = event["stages"][index + 1]
        if "fromGroups" in next_spec:
            promoted = [
                promoted[i] for i in next_spec["fromGroups"] if i < len(promoted)
            ]
        begin(c, event, event["direct"].get(str(index + 1), []) + promoted)
    else:
        finish(c, event, [t for t in promoted if event["entries"].get(t) != "withdrawn"])


def leave(c, event, team, pack, reason):
    state = event["entries"].get(team)
    require(event["status"] in ("registration", "playing") and
            state in registrations.COMMITTED | {"invited", "offered", "waiting"},
            "Нет действующего участия в этом турнире")
    locked = event["status"] == "playing" or c["date"] >= event["lock"]
    event["entries"][team] = "withdrawn" if locked else "declined"
    event.setdefault("reasons", {})[team] = reason
    if team == c["team"]:
        notice(c, event, "Снятие с турнира" if locked else "Отказ от участия", reason)
    if not locked:
        if event.get("invitePools") and not event.get("inviteClosed"):
            refill_invites(c, event)
        if event.get("waiting"):
            select_applicants(c, event, pack)
        return
    for draws in event["draws"]:
        for draw in draws:
            if draw["format"] == "swiss" and team in draw["teams"]:
                withdrawn = draw.setdefault("withdrawn", [])
                if team not in withdrawn:
                    withdrawn.append(team)
    # Existing games stay in the historical draw. Advance their opponents
    # administratively, without recording played maps, VRS or player stats.
    while fixture := next((f for f in c["queue"] if f.get("edition") == event["id"] and team in f["teams"]), None):
        draw = event["draws"][fixture["stage"]][fixture["group"]]
        winner = next(t for t in fixture["teams"] if t != team)
        stages.record(draw, fixture["game"], winner, team)
        if winner == c["team"]:
            notice(c, event, "Техническая победа", "Соперник снялся с матча " + fixture["date"])
        draw["games"][fixture["game"]].update(administrative=True, reason=reason)
        c["queue"].remove(fixture)
        if c.get("watchFixture") == fixture["id"]:
            c.pop("watchFixture")
        schedule_draw(c, event)
    if event["status"] == "finished":
        publish(c, pack)


def priority_for(event, team):
    # A place already earned or a stage already under way is more costly to relinquish.
    state = event["entries"].get(team)
    return (event["prestige"], -len(event["draws"]), state not in ("qualified", "locked"),
            not bool(event.get("feeds")), -sum(event["prizes"]), event["id"])


def resolve_slots(c):
    """Only modeled online windows allow a later day in the same round."""
    events = c["circuit"]["editions"]
    for f in c["queue"]:
        if "edition" not in f:
            continue
        e = events[f["edition"]]
        spec = e["stages"][f["stage"]]
        if not registrations.flexible_round(e,spec):
            continue
        occupied = {g["date"] for g in c["queue"] if g.get("edition") != e["id"] and set(f["teams"]).intersection(g["teams"])}
        if f["date"] not in occupied:
            continue
        draw = e["draws"][f["stage"]][f["group"]]
        row = draw["games"][f["game"]]
        # Stop before a dependent round can begin, including unpublished games.
        rounds = max(g["round"] for g in draw["games"])
        limit = registrations.round_deadline(spec, row["round"], rounds)
        candidate = offset(f["date"], 1)
        while candidate <= limit:
            if candidate not in occupied and not any(g is not f and g["date"] == candidate and
                    set(f["teams"]).intersection(g["teams"]) for g in c["queue"]):
                f["date"] = row["date"] = candidate
                if c["team"] in f["teams"]:
                    notice(c, e, "Изменение расписания", "Свободный игровой день: " + candidate)
                break
            candidate = offset(candidate, 1)
    order(c)


def fixture_conflicts(c, fixture):
    return [f for f in c["queue"] if f.get("edition") and f["edition"] != fixture.get("edition")
            and f["date"] == fixture["date"] and set(f["teams"]).intersection(fixture["teams"])]


def settle_fixture_conflicts(c, fixture, pack):
    # A later draw can create a new clash after both entries were accepted.
    resolve_slots(c)
    for other in fixture_conflicts(c, fixture):
        for team in sorted(set(other["teams"]).intersection(fixture["teams"])):
            if team == c["team"]:
                c.update(progress=None, error="Конфликт календаря. Выберите приоритет на странице соревнования → Моя заявка.")
                return
            events = c["circuit"]["editions"]
            lost = max((events[other["edition"]], events[fixture["edition"]]), key=lambda e:priority_for(e,team))
            leave(c, lost, team, pack, "Совпадение обязательных матчей")
            return


def tournament_priority(event):
    return (event["prestige"], -sum(event["prizes"]), event["start"], event["id"])


def qualification_conflict(c, target, team):
    commitments = [c["circuit"]["editions"][r["id"]] for r in registrations.clashes(c, target, team)]
    if not commitments:
        return None
    for other in commitments:
        if (
            team == c["team"]
            or other["lock"] <= c["date"]
            or priority_for(other, team) <= priority_for(target, team)
        ):
            return other
    for other in commitments:
        # Only unlocked commitments reach this path. Refill an existing
        # invitation pool or waiting list without recalculating its seeding.
        leave(c, other, team, None, "Пройден отбор: " + target["title"])
    return None


def finish(c, event, promoted):
    if event["status"] == "finished":
        return
    event.update(status="finished", advanced=promoted)
    archive_result(c, event, promoted)
    if "feeds" in event:
        target = c["circuit"]["editions"][event["feeds"]]
        for slot, team in enumerate(promoted):
            if "targetStages" in event:
                stage = str(event["targetStages"][slot])
                target["direct"].setdefault(stage, []).append(team)
                target.setdefault("qualifiedStages", {})[team] = stage
                target.setdefault("inviteRegions", {})[team] = event["region"]
            previous = event["registrations"][team][-1]
            target.setdefault("qualification", {})[team] = dict(
                edition=event["id"], version=previous["version"]
            )
            clash = registrations.player_conflict(
                c, target, team, previous["players"], previous["reserves"]
            ) or qualification_conflict(c, target, team)
            if clash:
                target["entries"][team] = "invited" if team == c["team"] else "declined"
                target.setdefault("reasons", {})[team] = (
                    "Пересечение дат: " + clash["title"]
                )
            else:
                target["entries"][team] = "qualified"
                target["registrations"].setdefault(team, []).append(
                    dict(
                        deepcopy(previous),
                        version=len(target["registrations"].get(team, [])) + 1,
                        date=c["date"],
                        reason=None,
                    )
                )
            for sibling in c["circuit"]["editions"].values():
                if (
                    sibling is not event
                    and sibling.get("feeds") == target["id"]
                    and sibling["status"] == "registration"
                ):
                    if team in sibling["entries"]:
                        sibling["entries"][team] = "qualifiedElsewhere"
            if team == c["team"]:
                notice(
                    c,
                    target,
                    "Квалификация пройдена",
                    (
                        "Выберите турнир из-за пересечения дат с " + clash["title"]
                        if clash
                        else "Создана заявка основного этапа. Её можно изменить до фиксации."
                    ),
                )
        if target["lock"] > c["date"] and all(
            e["status"] in ("finished", "cancelled")
            for e in c["circuit"]["editions"].values()
            if e.get("feeds") == target["id"]
        ):
            clock(c, target["lock"], "Фиксация состава основного этапа", target)


def archive_result(c, event, promoted):
    placements = list(promoted)
    for draws in reversed(event["draws"]):
        for draw in draws:
            if draw["format"] == "swiss":
                placements.extend(
                    r["team"] for r in stages.table(draw) if r["team"] not in placements
                )
                continue
            games = list(reversed(draw["games"]))
            for g in games:
                if g["label"] == "За третье место":
                    continue
                loser = g.get("loser")
                if loser and loser not in placements:
                    placements.append(loser)
            bronze = next((g for g in games if g["label"] == "За третье место"), None)
            if bronze:
                placements[2:4] = [bronze["winner"], bronze["loser"]]
    event["placements"] = placements
    event["payouts"] = {
        t: p + bonus
        for t, p, bonus in zip(
            placements,
            event["prizes"],
            event.get("clubRewards", [0] * len(event["prizes"])),
        )
    }
    if event["payouts"]:
        c["circuit"]["awards"][event["id"]] = event["payouts"].copy()
    if event["stats"]:
        event["mvp"] = max(
            event["stats"],
            key=lambda p: (
                event["stats"][p]["damage"] / event["stats"][p]["rounds"],
                event["stats"][p]["k"],
                p,
            ),
        )
    if c["team"] in placements and "feeds" not in event:
        notice(
            c, event, "Турнир завершён", f"Место: {placements.index(c['team']) + 1}."
        )


def completed(c, e, report):
    event = c["circuit"]["editions"][e["edition"]]
    draw = event["draws"][e["stage"]][e["group"]]
    winner = report["winnerTeamId"]
    stages.record(draw, e["game"], winner, next(t for t in e["teams"] if t != winner))
    row = draw["games"][e["game"]]
    row["score"] = report["score"]
    if draw["format"] == "roundRobin":
        counts = Counter(r["winnerTeamId"] for r in report["rounds"])
        row["roundScore"] = [counts[t] for t in e["teams"]]
    for row in report["stats"]:
        target = event["stats"].setdefault(
            row["player"],
            dict(
                team=row["teamId"], name=row["name"], rounds=0, k=0, d=0, a=0, damage=0
            ),
        )
        for key in ("k", "d", "a", "damage"):
            target[key] += row[key]
        target["rounds"] += len(report["rounds"])
    schedule_draw(c, event)


def tick(c, pack):
    if day(c["date"]).weekday() == 0 and day(c["date"]).day <= 7:
        publish(c, pack)
        c["circuit"]["snapshots"][c["date"]] = deepcopy(
            c["circuit"].get("live", {}).get("rows", [])
        )
    if c["date"].endswith("-01-01"):
        add_season(c, pack, int(c["date"][:4]))
    else:
        for event in c["circuit"]["editions"].values():
            if (
                event["admission"] == "qualified"
                and event["status"] == "registration"
                and event["lock"] <= c["date"]
            ):
                lock(c, event, pack)
        process_day(c, pack)


def publish(c, pack):
    from .competition_catalog import DATA
    import json

    events = {
        e["id"]: dict(
            end=e["end"],
            lastMatch=max(
                (
                    g.get("date", e["end"])
                    for d in e["draws"]
                    for group in d
                    for g in group["games"]
                    if "fixture" in g
                ),
                default=e["end"],
            ),
            lan=e.get("lan", e["region"] == "Global"),
            pool=sum(e["prizes"]) + sum(e.get("clubRewards", [])),
            payouts=e.get("payouts", {}),
            linked=e.get("feeds"),
        )
        for e in c["circuit"]["editions"].values()
        if e["status"] == "finished"
    }
    matches = []
    for e in c["history"]:
        if e.get("edition") not in events:
            continue
        event = c["circuit"]["editions"][e["edition"]]
        matches.append(
            dict(
                date=e["date"],
                event=e["edition"],
                teams=e["teams"],
                winner=e["winnerTeamId"],
                ranked=event["admission"] != "open",
                fives=[
                    event["registrations"][t][e["rosterVersions"][t] - 1]["players"]
                    for t in e["teams"]
                ],
            )
        )
    for eid in events:
        event = c["circuit"]["editions"][eid]
        for draws in event["draws"]:
            for draw in draws:
                for game in draw["games"]:
                    if game.get("historical"):
                        teams = game["slots"]
                        matches.append(
                            dict(
                                date=game["date"],
                                event=eid,
                                teams=teams,
                                winner=game["winner"],
                                ranked=True,
                                fives=[
                                    event["registrations"][t][0]["players"]
                                    for t in teams
                                ],
                            )
                        )
    raw = vrs.history()
    countries = {p: row["country"] for p, row in raw["players"].items()}
    countries.update(
        {
            p: r["nationality"]
            for p, r in pack["players"].items()
            if r["nationality"] in vrs.country_regions()
        }
    )
    rows = vrs.calculate(
        raw["matches"] + matches,
        {**raw["events"], **events},
        c["date"],
        countries,
        json.loads((DATA / "vrs-regions.json").read_bytes()),
        {p: r["name"] for p, r in pack["players"].items()},
    )
    for r in rows:
        org = r["team"]
        if org in pack["teams"]:
            r["name"] = pack["teams"][org]["name"]
        else:
            r.update(name=raw["clubs"][org]["name"], team=raw["clubs"][org]["team"])
    c["circuit"]["live"] = {"date": c["date"], "rows": rows, "completeWindow": True}


def last_chance(c, major, pack):
    """Run regional qualifiers for the unfilled invitation slots of this edition."""
    from .competition_catalog import edition, phase

    major["inviteClosed"] = True
    regions = ("Europe", "Americas", "Asia")
    missing = defaultdict(list)
    for index, group in enumerate(major.get("invitePools", [])):
        stage = group["stage"]
        region = regions[index % 3]
        taken = sum(
            major["inviteRegions"].get(t) == region
            and major["entries"].get(t) in ("accepted", "locked", "qualified")
            for t in major["direct"][str(stage)]
        )
        missing[region].extend([stage] * max(0, group["count"] - taken))
    for region, stages_needed in missing.items():
        if not stages_needed:
            continue
        eid = major["id"] + "-lcq-" + region
        if eid in c["circuit"]["editions"]:
            continue
        played = offset(major["lock"], -1)
        q = edition(
            eid,
            "major-lcq",
            major["title"] + " · последний региональный отбор " + region,
            major["organizer"],
            major["source"],
            "Онлайн · " + region,
            region,
            2,
            c["date"],
            played,
            [
                phase(
                    "Региональный отбор",
                    "single",
                    played,
                    played,
                    3,
                    len(stages_needed),
                )
            ],
            [],
            capacity=128,
            admission="open",
            feeds=major["id"],
            targetStages=stages_needed,
            simulated=True,
            year=major["year"],
            lan=False,
        )
        c["circuit"]["editions"][eid] = q
        for stamp in (played, offset(played, -1)):
            if stamp > c["date"]:
                clock(c, stamp, "Последний отбор на Major")
        if c["team"] in selected(c, q, pack) and c["team"] not in major["invites"]:
            notice(
                c,
                q,
                "Открыт последний отбор",
                "Свободных мест: " + str(len(stages_needed)),
            )
        auto_register(c, q, pack)


def missing_players(c, fixture, pack):
    if "edition" not in fixture:
        return {}
    edition = c["circuit"]["editions"][fixture["edition"]]
    return {
        t: missing
        for t in fixture["teams"]
        if (
            missing := set(edition["registrations"][t][-1]["players"])
            - set(registrations.available(c, t, pack))
        )
    }


def resolve_availability(c, fixture, pack, *, withdraw=False):
    """Apply eligible reserve requests or an administrative decision, without creating a match report."""
    edition = c["circuit"]["editions"][fixture["edition"]]
    absent = missing_players(c, fixture, pack)
    for team, missing in list(absent.items()):
        if team == c["team"] or len(missing) != 1:
            continue
        last = edition["registrations"][team][-1]
        outgoing = next(iter(missing))
        for incoming in last["reserves"]:
            if incoming not in registrations.available(c, team, pack):
                continue
            five = [incoming if p == outgoing else p for p in last["players"]]
            reserves = [outgoing if p == incoming else p for p in last["reserves"]]
            try:
                registrations.submit(
                    c,
                    edition,
                    team,
                    pack,
                    five,
                    reserves,
                    last["coach"],
                    reason="Игрок недоступен на дату матча",
                )
            except ValueError:
                continue
            del absent[team]
            break
    if not absent:
        return False
    if c["team"] in absent and not withdraw:
        c.update(
            progress=None,
            error="В заявке недоступен игрок. Подайте экстренную замену или снимитесь с матча.",
        )
        notice(c, edition, "Проблема с заявкой", c["error"])
        return True
    c["queue"].remove(fixture)
    draw = edition["draws"][fixture["stage"]][fixture["group"]]
    row = draw["games"][fixture["game"]]
    if len(absent) == 2:
        if draw["format"] == "swiss":
            draw.setdefault("withdrawn", []).extend(absent)
        row.update(winner=None, loser=None)
    else:
        loser = next(iter(absent))
        winner = next(t for t in fixture["teams"] if t != loser)
        stages.record(draw, fixture["game"], winner, loser)
    row.update(administrative=True, reason="Невозможно выставить допущенную пятёрку")
    if c["team"] in fixture["teams"]:
        notice(c, edition, "Административное решение", row["reason"])
    schedule_draw(c, edition)
    if edition["status"] == "finished":
        publish(c, pack)
    return True
