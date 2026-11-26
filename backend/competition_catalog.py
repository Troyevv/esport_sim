"""Dated event profiles. Each career retains a copy of its edition and regulations."""

import gzip
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from . import veto

DATA = Path(__file__).with_name("data") / "competitions"
PGL = "https://www.pglesports.com/cs2/pgl-major-singapore-2026/"
CCT = "https://cctour.gg/cct-2026-contenders-europe-12/"
ESL = "https://pro.eslgaming.com/tour/2026/05/esl-challenger-league-season-52-additional-information/"


@lru_cache(maxsize=1)
def seed_data():
    return json.loads(gzip.decompress((DATA / "november-2026.json.gz").read_bytes()))


def offset(day, delta):
    return (date.fromisoformat(day) + timedelta(days=delta)).isoformat()


def phase(name, format_, start, end, best=3, advance=1, **options):
    return dict(
        name=name,
        format=format_,
        start=start,
        end=end,
        bestOf=best,
        advance=advance,
        **options,
    )


def edition(
    key,
    series,
    title,
    operator,
    source,
    place,
    region,
    prestige,
    opens,
    lock,
    stages,
    prizes,
    **options,
):
    return dict(
        id=key,
        series=series,
        title=title,
        organizer=operator,
        source=source,
        place=place,
        region=region,
        prestige=prestige,
        opens=opens,
        lock=lock,
        start=stages[0]["start"],
        end=stages[-1]["end"],
        stages=stages,
        prizes=prizes,
        registrations={},
        entries={},
        draws=[],
        status="registration",
        direct={},
        stats={},
        rules=dict(
            version=1,
            reserves=1,
            core=3,
            timeouts=3,
            timeoutScope="map",
            pool=list(veto.ACTIVE),
            first="home",
            formats=veto.REGULATION["formats"].copy(),
            pickSide="opponent",
            deciderSide="second",
            id=series + ".202611.1",
        ),
        **options,
    )


def season(year):
    simulated = year != 2026

    def d(month_day):
        return str(year) + "-" + month_day

    key = f"cct-contenders-{year}"
    contenders = edition(
        key,
        "cct-contenders",
        "CCT Contenders Europe" + (" 12" if not simulated else f" · {year}"),
        "CCT",
        CCT,
        "Онлайн · Европа",
        "Europe",
        3,
        d("11-21"),
        d("12-13"),
        [phase("Основной этап", "double", d("12-13"), d("12-21"))],
        [1250, 750, 500],
        capacity=16,
        admission="qualified",
    )
    editions = [contenders]
    for n in (1, 2):
        day = d("12-0" + str(n + 4))
        editions.append(
            edition(
                key + f"-oq{n}",
                "cct-oq",
                contenders["title"] + f" · открытая квалификация {n}",
                "CCT",
                CCT,
                "Онлайн · Европа",
                "Europe",
                3,
                d("11-21"),
                day,
                [phase("Открытый отбор", "single", day, day, 1, 8)],
                [],
                capacity=128,
                admission="open",
                feeds=key,
            )
        )
    for number, start, end in [(13, "12-03", "12-05"), (14, "12-07", "12-09")]:
        editions.append(
            edition(
                f"ecl-eu-{year}-{number}",
                "ecl-europe",
                f"ESL Challenger League · Europe Cup {number}",
                "ESL",
                ESL,
                "Онлайн · Европа",
                "Europe",
                2,
                d("11-25"),
                d(start),
                [
                    phase(
                        "Группы GSL", "gsl", d(start), offset(d(start), 1), advance=8
                    ),
                    phase(
                        "Плей-офф", "single", offset(d(start), 1), d(end), bronze=True
                    ),
                ],
                [4000, 2000, 1000],
                capacity=16,
                admission="rankedOpen",
                applyBy=offset(d(start), -3),
                seedDate=d("11-15"),
                feederGroup="Europe",
                finals=f"ecl-finals-{year}-Europe",
            )
        )
    for code, region, size, amounts in [
        ("North America", "Americas", 16, [8000, 4000, 2000, 1500, 1000, 1000]),
        ("South America", "Americas", 16, [8000, 4000, 2000, 1500, 1000, 1000]),
        ("Asia", "Asia", 16, [5000, 2500, 1500, 1000]),
        ("Oceania", "Asia", 10, [1500, 1000]),
    ]:
        finals = "Asia-Oceania" if region == "Asia" else code
        slug = code.lower().replace(" ", "-")
        editions.append(
            edition(
                f"ecl-{slug}-{year}-4",
                "ecl-regional",
                f"ESL Challenger League · {code} Cup 4",
                "ESL",
                ESL,
                "Онлайн · " + code,
                region,
                2,
                d("11-02"),
                d("12-01"),
                [phase("Основной этап", "double", d("12-03"), d("12-10"))],
                amounts,
                capacity=size,
                admission="regionalInvite",
                subregion=code,
                seedDate=d("11-15"),
                feederGroup=finals,
                finals=f"ecl-finals-{year}-{finals}",
                wildcards=2,
            )
        )
    for code, region, size, start in [
        ("Europe", "Europe", 16, "12-14"),
        ("North America", "Americas", 4, "12-16"),
        ("South America", "Americas", 4, "12-16"),
        ("Asia-Oceania", "Asia", 8, "12-15"),
    ]:
        editions.append(
            edition(
                f"ecl-finals-{year}-{code}",
                "ecl-finals",
                f"ESL Challenger League · {code} Regional Finals",
                "ESL",
                ESL,
                "Онлайн · " + code,
                region,
                2,
                d("12-11"),
                d("12-13"),
                [phase("Плей-офф", "single", d(start), d("12-18"), finalBO=5)],
                [2000] if code == "Europe" else [],
                capacity=size,
                admission="finalsInvite",
                subregion=code,
                feederGroup=code,
                seedDate=d("12-11"),
            )
        )
    major = edition(
        f"pgl-major-{year}",
        "pgl-major",
        "PGL Major Singapore 2026" if not simulated else f"PGL Major · {year}",
        "PGL",
        PGL,
        "Singapore Indoor Stadium" if not simulated else "LAN",
        "Global",
        1,
        d("11-02"),
        d("11-06"),
        [
            phase(
                "Стадия 1",
                "swiss",
                d("11-24"),
                d("11-27"),
                1,
                8,
                roundDays=[0, 0, 1, 2, 3],
            ),
            phase(
                "Стадия 2",
                "swiss",
                d("11-28"),
                d("12-01"),
                1,
                8,
                roundDays=[0, 0, 1, 2, 3],
            ),
            phase(
                "Стадия 3",
                "swiss",
                d("12-02"),
                d("12-06"),
                3,
                8,
                roundDays=[0, 1, 2, 3, 4],
            ),
            phase("Плей-офф", "single", d("12-10"), d("12-13"), bronze=True, finalBO=5),
        ],
        [500000, 170000, 100000, 60000] + [45000] * 4 + [20000] * 8 + [10000] * 8,
        capacity=32,
        admission="invitation",
    )
    major["rules"].update(core=5)
    major["rules"]["formats"]["1"] = [
        dict(kind="ban", actor=i) for i in (0, 0, 1, 1, 1, 0)
    ]
    major["rules"]["formats"]["3"] = [
        dict(kind=k, actor=i)
        for k, i in zip(
            ("ban", "ban", "pick", "pick", "ban", "ban"),
            (0, 1, 0, 1, 1, 0),
            strict=True,
        )
    ]
    editions.append(draculan(year))
    if year == 2026:
        editions.append(major)
    for event in editions:
        event.update(simulated=simulated, year=year)
    if year >= 2027:
        editions.extend(pro_league(year))
        editions.extend(iem_usa(year))
        editions.extend(seasonal_cups(year, editions))
        editions.append(rivals(year))
        editions.extend(announced_lans(year))
        editions.extend(next_majors(year, major))
    return editions


def pro_league(year):
    result = []
    prizes = (
        [125000, 50000, 30000, 20000]
        + [10000] * 4
        + [6000] * 3
        + [4000] * 3
        + [2500] * 2
    )
    for number, opens, start, playoffs, end, club in [
        (
            25,
            "01-04",
            "03-06",
            "03-12",
            "03-14",
            [240000, 160000, 130000, 100000]
            + [50000] * 4
            + [25000] * 3
            + [15000] * 3
            + [0] * 2,
        ),
        (
            26,
            "08-02",
            "09-25",
            "10-01",
            "10-03",
            [175000, 120000, 90000, 65000]
            + [40000] * 4
            + [20000] * 3
            + [10000] * 3
            + [0] * 2,
        ),
    ]:
        stamp = lambda md: f"{year}-{md}"
        publication = stamp(opens[:2] + "-01")
        publication = offset(
            publication, (-date.fromisoformat(publication).weekday()) % 7
        )
        event = edition(
            f"epl-{year}-{number}",
            "epl",
            f"ESL Pro League Season {number}"
            if year == 2027
            else f"ESL Pro League · {year} / {number - 24}",
            "ESL",
            f"https://pro.eslgaming.com/tour/2026/{'05' if number == 25 else '11'}/esl-pro-league-season-{number}-additional-information/",
            "Саудовская Аравия · LAN" if number == 25 else "Европа · Шенгенская зона",
            "Global",
            1,
            publication,
            offset(stamp(start), -7),
            [
                phase(
                    "Групповой этап",
                    "swiss",
                    stamp(start),
                    offset(stamp(playoffs), -1),
                    3,
                    8,
                ),
                phase(
                    "Плей-офф",
                    "single",
                    stamp(playoffs),
                    stamp(end),
                    bronze=True,
                    finalBO=5,
                ),
            ],
            prizes,
            capacity=16,
            admission="leagueInvite",
            clubRewards=club,
            year=year,
            simulated=year != 2027,
            seedDate=stamp("02-15" if number == 25 else "09-15"),
            modelDeadlines=True,
            wildcardCount=1 if number == 26 else 0,
            feederYear=year - 1 if number == 25 else year,
            half="winter" if number == 25 else "spring",
        )
        result.append(event)
    return result


def seasonal_cups(year, templates):
    # Simulated editions use the published competition families. Two extra cycles keep
    # qualification open between the historical winter windows.
    from copy import deepcopy

    result = []
    for label, delta in [("spring", -226), ("summer", -112)]:
        for original in templates:
            if original["series"] in (
                "epl",
                "pgl-major",
                "iem-usa",
                "iem-closed",
            ):
                continue
            event = deepcopy(original)
            event.update(
                id=event["id"] + "-" + label,
                title=event["title"]
                + " · "
                + ("Весна" if label == "spring" else "Лето"),
                simulated=True,
            )
            for key in ("opens", "lock", "start", "end", "seedDate", "applyBy"):
                if key in event:
                    event[key] = offset(event[key], delta)
            for stage in event["stages"]:
                for key in ("start", "end"):
                    stage[key] = offset(stage[key], delta)
            for key in ("feeds", "finals"):
                if key in event:
                    event[key] += "-" + label
            result.append(event)
    return result


def iem_usa(year):
    source = "https://pro.eslgaming.com/tour/2026/06/iem-usa-additional-information/"
    y = str(year)
    publication = offset(y + "-01-01", (-date(year, 1, 1).weekday()) % 7)
    tournament = edition(
        "iem-usa-" + y,
        "iem-usa",
        "IEM USA " + y,
        "ESL",
        source,
        "США · LAN",
        "Global",
        1,
        publication,
        y + "-03-31",
        [
            phase(
                "Групповой этап", "doubleGroups", y + "-04-05", y + "-04-08", advance=8
            ),
            phase(
                "Плей-офф", "single", y + "-04-09", y + "-04-11", bronze=True, finalBO=5
            ),
        ],
        [120000, 50000, 30000, 20000] + [10000] * 4 + [6000] * 4 + [4000] * 4,
        capacity=16,
        admission="mixedInvite",
        clubRewards=[180000, 120000, 90000, 65000]
        + [40000] * 4
        + [21250] * 4
        + [0] * 4,
        year=year,
        simulated=year != 2027,
        seedDate=y + "-03-15",
    )
    events = [tournament]
    for region, advance in [("Global", 2), ("Americas", 1)]:
        title = f"IEM USA {y} · закрытая квалификация {region}"
        events.append(
            edition(
                tournament["id"] + "-" + region,
                "iem-closed",
                title,
                "ESL",
                source,
                "Онлайн · " + ("Европа" if region == "Global" else "Америка"),
                region,
                2,
                offset(publication, 1),
                y + "-02-15",
                [
                    phase(
                        "Закрытая квалификация",
                        "single",
                        y + "-02-16",
                        y + "-02-18",
                        advance=advance,
                    )
                ],
                [],
                admission="closedInvite",
                capacity=8,
                feeds=tournament["id"],
                year=year,
                simulated=year != 2027,
                lan=False,
                modelDates=True, reschedule="withinRound",
            )
        )
    return events


def rivals(year):
    y = str(year)
    return edition(
        "blast-rivals-" + y,
        "blast-rivals",
        "BLAST Rivals Hong Kong " + y,
        "BLAST",
        "https://assets.blast.tv/rulebook/BLAST_Premier_Handbook_2027.pdf",
        "AsiaWorld-Arena · Гонконг",
        "Global",
        1,
        y + "-09-07",
        y + "-10-25",
        [
            phase(
                "Группы GSL",
                "gsl",
                y + "-11-10",
                y + "-11-11",
                advance=6,
                groups=2,
                groupSeeds=[[0, 3, 4, 7], [1, 2, 5, 6]],
            ),
            phase(
                "Плей-офф",
                "single",
                y + "-11-12",
                y + "-11-14",
                finalBO=5,
                fromGroups=[0, 3, 1, 4, 2, 5],
            ),
        ],
        [150000, 100000, 60000, 60000, 40000, 40000, 25000, 25000],
        clubRewards=[150000, 125000, 100000, 100000, 80000, 80000, 57500, 57500],
        capacity=8,
        wildcardCount=4,
        admission="globalInvite",
        year=year,
        simulated=year != 2027,
        modelDeadlines=True,
    )


def announced_lans(year):
    y = str(year)
    day = lambda md: y + "-" + md
    main = edition(
        "blast-open-" + y,
        "blast-open",
        "BLAST Premier Open 3 · USA " + y,
        "BLAST",
        "https://blast.tv/blast-premier-open-3-2027-announcement",
        "США · LAN",
        "Global",
        1,
        day("05-04"),
        day("08-27"),
        [
            phase("Play-in", "swiss", day("09-05"), day("09-09"), 3, 8),
            phase("Арена", "single", day("09-10"), day("09-12"), finalBO=5),
        ],
        [160000, 90000] + [40000] * 2 + [20000] * 4 + [15000] * 3 + [10000] * 5,
        clubRewards=[240000, 110000]
        + [60000] * 2
        + [30250] * 4
        + [23000] * 3
        + [15000] * 3
        + [10000] * 2,
        capacity=16,
        admission="globalInvite",
        inviteCount=11,
        seedDate=day("07-05"),
        rescind=day("05-18"),
    )
    events = [main]
    for region, sub in [
        ("Europe", "Europe"),
        ("Americas", "North America"),
        ("Americas", "South America"),
        ("Asia", "Asia-Pacific"),
    ]:
        slug = sub.lower().replace(" ", "-")
        host = sub == "North America"
        name = main["title"] + " · " + sub
        cq = edition(
            main["id"] + "-cq-" + slug,
            "blast-closed",
            name + " · закрытая квалификация",
            "BLAST",
            main["source"],
            "Онлайн · " + sub,
            region,
            2,
            day("05-04"),
            day("07-05"),
            [
                phase(
                    "Группы и решающие матчи" if host else "Плей-офф",
                    "double" if host else "single",
                    day("07-08") if host else day("07-09"),
                    day("07-11"),
                    3,
                    2 if host else 1,
                )
            ],
            [],
            capacity=8,
            subregion=sub,
            admission="closedInvite",
            inviteCount=4,
            feeds=main["id"],
            seedDate=day("06-08"),
            lan=False,
        )
        if host:
            cq["stages"] = [
                phase("Группы GSL", "gsl", day("07-08"), day("07-10"), 3, 4, groups=2),
                phase(
                    "Решающие матчи",
                    "single",
                    day("07-11"),
                    day("07-11"),
                    3,
                    2,
                    fromGroups=[0, 2, 1, 3],
                ),
            ]
        oq = edition(
            main["id"] + "-oq-" + slug,
            "blast-open-qualifier",
            name + " · открытая квалификация",
            "BLAST",
            main["source"],
            "Онлайн · " + sub,
            region,
            3,
            day("06-01"),
            day("07-01"),
            [phase("Открытый отбор", "single", day("07-01"), day("07-03"), 1, 4)],
            [],
            capacity=128,
            subregion=sub,
            admission="open",
            feeds=cq["id"],
            modelDates=True, reschedule="withinRound",
            lan=False,
        )
        events.extend([cq, oq])
    krakow = edition(
        "iem-krakow-" + y,
        "iem-krakow",
        "IEM Kraków " + y,
        "ESL",
        "https://pro.eslgaming.com/tour/2026/03/2027-updates-iem-krakow-2027-additional-information/",
        "TAURON Arena · Краков",
        "Global",
        1,
        offset(day("01-01"), (-date(year, 1, 1).weekday()) % 7),
        day("01-20"),
        [
            phase("Play-in", "double", day("01-27"), day("01-29"), 3, 8),
            phase(
                "Групповой этап", "doubleGroups", day("02-01"), day("02-03"), advance=8
            ),
            phase(
                "Арена", "single", day("02-04"), day("02-07"), bronze=True, finalBO=5
            ),
        ],
        [420000, 200000, 100000, 50000]
        + [25000] * 4
        + [15000] * 4
        + [10000] * 4
        + [5000] * 4
        + [2500] * 4,
        clubRewards=[80000, 40000, 30000, 20000] + [15000] * 4 + [5000] * 4 + [0] * 12,
        capacity=24,
        admission="globalInvite",
        stageSlots=[(1, 8), (0, 16)],
        modelDeadlines=True,
    )
    events.append(krakow)
    for e in events:
        e.update(year=year, simulated=year != 2027)
    return events


def cct_europe(year):
    y = str(year)
    source = "https://cctour.gg/cct-2026-europe-16/"
    series = "CCT Europe Series 16" if year == 2026 else f"CCT Europe Series · {year}"
    main = edition(
        "cct-europe-" + y,
        "cct-europe",
        series,
        "CCT",
        source,
        "Онлайн · Европа",
        "Europe",
        2,
        y + "-10-26",
        y + "-12-01",
        [
            phase(
                "Основной этап",
                "swiss",
                y + "-12-01",
                y + "-12-09",
                3,
                8,
                roundDays=[0, 2, 4, 6, 8],
            ),
            phase("Плей-офф", "single", y + "-12-10", y + "-12-13"),
        ],
        [10000, 5000, 2500, 2500] + [1250] * 4,
        capacity=24,
        admission="globalInvite",
        stageSlots=[(1, 8), (0, 12)],
        minRegional=9,
        seedDate=y + "-10-26",
        modelDeadlines=True,
    )
    qualifier = edition(
        main["id"] + "-playin",
        "cct-europe-playin",
        series + " · закрытая квалификация",
        "CCT",
        source,
        "Онлайн · Европа",
        "Europe",
        2,
        y + "-10-26",
        y + "-11-25",
        [
            phase(
                "Группы GSL",
                "gsl",
                y + "-11-25",
                y + "-11-29",
                advance=8,
                groupDays=[[0, 1, 4], [0, 1, 4], [2, 3, 4], [2, 3, 4]],
            ),
            phase("Решающие матчи", "single", y + "-11-30", y + "-11-30", advance=4),
        ],
        [],
        capacity=16,
        admission="closedInvite",
        feeds=main["id"],
        targetStages=[0] * 4,
        minRegional=9,
        seedDate=y + "-10-26",
        modelDeadlines=True,
    )
    for e in (main, qualifier):
        e.update(year=year, simulated=year != 2026, lan=False)
    return [main, qualifier]


def next_majors(year, template):
    from copy import deepcopy

    events = []
    for key, title, organizer, town, source, start, finish, month in [
        (
            "fire-major",
            "FiReMAJOR Buenos Aires",
            "FiReSPORTS",
            "Буэнос-Айрес · Usina del Arte / Movistar Arena",
            "https://www.hltv.org/events/8297/firemajor-buenos-aires-2027",
            "05-31",
            "06-20",
            "04",
        ),
        (
            "pw-major",
            "Perfect World Shanghai Major",
            "Perfect World",
            "Шанхай · Китай",
            "https://english.shanghai.gov.cn/en-Latest-WhatsNew/20260920/3b611deb78c348c19ad3d096312a4f9d.html",
            "11-22",
            "12-12",
            "10",
        ),
    ]:
        if year == 2028:
            start, finish = (
                ("05-29", "06-18") if key == "fire-major" else ("11-20", "12-10")
            )
        start = f"{year}-{start}"
        end = f"{year}-{finish}"
        opened = f"{year}-{month}-01"
        event = deepcopy(template)
        event.update(
            id=f"{key}-{year}",
            series=key,
            title=title + " " + str(year)
            if year == 2027
            else organizer + " Major · " + str(year),
            organizer=organizer,
            place=town if year == 2027 else "LAN",
            source=source,
            start=start,
            end=end,
            opens=offset(opened, (-date.fromisoformat(opened).weekday()) % 7),
            lock=offset(start, -16),
            modelDeadlines=True,
            modelStages=True,
            year=year,
            simulated=year != 2027,
            prizes=[500000, 170000, 80000, 80000]
            + [45000] * 4
            + [15000] * 8
            + [10000] * 8
            + [5000] * 8,
            stages=[
                phase(
                    "Стадия 1",
                    "swiss",
                    start,
                    offset(start, 3),
                    1,
                    8,
                    roundDays=[0, 0, 1, 2, 3],
                ),
                phase(
                    "Стадия 2",
                    "swiss",
                    offset(start, 4),
                    offset(start, 7),
                    1,
                    8,
                    roundDays=[0, 0, 1, 2, 3],
                ),
                phase(
                    "Стадия 3",
                    "swiss",
                    offset(start, 8),
                    offset(start, 12),
                    1,
                    8,
                    roundDays=[0, 1, 2, 3, 4],
                ),
                phase("Плей-офф", "single", offset(end, -3), end, 3, 1, finalBO=5),
            ],
        )
        event["rules"]["id"] = f"{key}.202611.1"
        events.append(event)
    return events


def draculan(year):
    y = str(year)
    return edition(
        "draculan-" + y,
        "draculan",
        "DraculaN Season 8" if year == 2026 else "DraculaN · " + y,
        "Digital Crusade",
        "https://draculan.gg/",
        "Nexus Esports Hub · Бухарест",
        "Global",
        2,
        y + "-11-19",
        y + "-12-08",
        [
            phase(
                "Групповой этап и матчи за второе место",
                "roundRobin",
                y + "-12-15",
                y + "-12-17",
                1,
                16,
                groupSize=3,
                secondPlaceBO=3,
            ),
            phase("Плей-офф", "double", y + "-12-18", y + "-12-20", 3),
        ],
        [20000, 12500, 7500, 5000, 2500, 2500],
        capacity=24,
        admission="firstCome",
        minTeams=8,
        poolBySize=[[8, 27000], [16, 39000], [24, 50000]],
        shares=[40, 25, 15, 10, 5, 5],
        singleOrganization=True,
        bookingFee="1 500 € + НДС",
        lan=True,
        seedDate=y + "-12-08",
        year=year,
        simulated=year != 2026,
    )
