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
    return json.loads(gzip.decompress((DATA/"november-2026.json.gz").read_bytes()))


def offset(day, delta):
    return (date.fromisoformat(day) + timedelta(days=delta)).isoformat()


def phase(name, format_, start, end, best=3, advance=1, **options):
    return dict(name=name, format=format_, start=start, end=end, bestOf=best, advance=advance, **options)


def edition(key, series, title, operator, source, place, region, prestige, opens, lock, stages, prizes, **options):
    return dict(id=key, series=series, title=title, organizer=operator, source=source, place=place,
                region=region, prestige=prestige, opens=opens, lock=lock, start=stages[0]["start"],
                end=stages[-1]["end"], stages=stages, prizes=prizes, registrations={}, entries={},
                draws=[], status="registration", direct={}, stats={}, rules=dict(
                    version=1, reserves=1, core=3, timeouts=3, timeoutScope="map",
                    pool=list(veto.ACTIVE), first="home", formats=veto.REGULATION["formats"].copy(),
                    pickSide="opponent", deciderSide="second", id=series+".202611.1"),
                **options)


def season(year):
    simulated = year != 2026
    def d(month_day):
        return str(year)+"-"+month_day
    key = f"cct-contenders-{year}"
    contenders = edition(key,"cct-contenders","CCT Contenders Europe"+(" 12" if not simulated else f" · {year}"),
        "CCT",CCT,"Онлайн · Европа","Europe",3,d("11-21"),d("12-13"),
        [phase("Основной этап","double",d("12-13"),d("12-21"))], [1250,750,500], capacity=16, admission="qualified")
    editions = [contenders]
    for n in (1,2):
        day = d("12-0"+str(n+4))
        editions.append(edition(key+f"-oq{n}","cct-oq",contenders["title"]+f" · открытая квалификация {n}",
            "CCT",CCT,"Онлайн · Европа","Europe",3,d("11-21"),day,
            [phase("Открытый отбор","single",day,day,1,8)],[],capacity=128,admission="open", feeds=key))
    for number, start, end in [(13,"12-03","12-05"),(14,"12-07","12-09")]:
        editions.append(edition(f"ecl-eu-{year}-{number}","ecl-europe",f"ESL Challenger League · Europe Cup {number}",
            "ESL",ESL,"Онлайн · Европа","Europe",2,d("11-25"),d(start),[
                phase("Группы GSL","gsl",d(start),offset(d(start),1),advance=8),
                phase("Плей-офф","single",offset(d(start),1),d(end),bronze=True)],
            [4000,2000,1000],capacity=16,admission="rankedOpen"))
    major = edition(f"pgl-major-{year}","pgl-major",
        "PGL Major Singapore 2026" if not simulated else f"PGL Major · {year}", "PGL",PGL,
        "Singapore Indoor Stadium" if not simulated else "LAN","Global",1,d("11-02"),d("11-09"),[
            phase("Стадия 1","swiss",d("11-24"),d("11-27"),1,8,roundDays=[0,0,1,2,3]),
            phase("Стадия 2","swiss",d("11-28"),d("12-01"),1,8,roundDays=[0,0,1,2,3]),
            phase("Стадия 3","swiss",d("12-02"),d("12-06"),3,8,roundDays=[0,1,2,3,4]),
            phase("Плей-офф","single",d("12-10"),d("12-13"),bronze=True,finalBO=5)],
        [500000,170000,100000,60000]+[45000]*4+[20000]*8+[10000]*8,
        capacity=32,admission="invitation")
    major["rules"].update(core=5)
    major["rules"]["formats"]["1"] = [dict(kind="ban",actor=i) for i in (0,0,1,1,1,0)]
    major["rules"]["formats"]["3"] = [dict(kind=k,actor=i) for k,i in
        zip(("ban","ban","pick","pick","ban","ban"),(0,1,0,1,1,0),strict=True)]
    editions.append(major)
    for event in editions:
        event.update(simulated=simulated,year=year)
    return editions
