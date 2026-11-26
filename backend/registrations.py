"""Roster versions and current employment have independent lifetimes."""
from .database import require


def conflicts(a, b):
    return a["start"] <= b["end"] and b["start"] <= a["end"]


def signup(c, event, team, pack):
    require(event["opens"] <= c["date"] < event["lock"], "Регистрация закрыта")
    require(event["admission"] in ("open","rankedOpen") or event["entries"].get(team)=="invited",
            "Нет приглашения или места из квалификации")
    require(event["region"] in ("Global",pack["teams"][team]["region"]), "Регион не соответствует регламенту")
    require(event["entries"].get(team) in (None,"invited","declined"), "Вы уже подтвердили участие")
    for other in c["circuit"]["editions"].values():
        if other is event or other["entries"].get(team) not in ("accepted","locked","qualified"):
            continue
        require(not conflicts(event, other), "Пересечение дат: "+other["title"])
        require(not (event.get("feeds") == other["id"]), "Команда уже прошла этот отбор")
    require(sum(s=="accepted" for s in event["entries"].values()) < event["capacity"]
            or event["admission"]=="rankedOpen","Все места заняты")
    event["entries"][team] = "accepted"


def available(c, team, pack):
    main = pack["rosters"][c["teams"][team]]["players"]
    bench = c["circuit"]["bench"].get(team,[])
    return list(dict.fromkeys([*main,*bench]))


def submit(c, event, team, pack, players, reserves, coach, *, reason=None):
    require(event["entries"].get(team) in ("accepted","locked","qualified"), "Участие не подтверждено")
    require(isinstance(players,list) and len(players)==5 and isinstance(reserves,list)
            and len(reserves)<=event["rules"]["reserves"],"Требуется пятёрка и допустимое число запасных")
    all_ids = players+reserves
    require(all(isinstance(p,str) for p in all_ids) and len(set(all_ids))==len(all_ids),
            "Игрок повторяется в заявке")
    allowed = available(c,team,pack)
    versions = event["registrations"].get(team,[])
    if reason is None:
        require(event["opens"] <= c["date"] < event["lock"], "Наступил Roster Lock")
        require(set(all_ids) <= set(allowed), "В заявке есть недоступный игрок")
    else:
        require(c["date"]>=event["lock"] and event["status"]!="finished" and versions and
                isinstance(reason,str) and 0<len(reason.strip())<=240,"Укажите основание замены после фиксации")
        old=versions[-1]
        incoming=set(players)-set(old["players"])
        outgoing=set(old["players"])-set(players)
        require(len(incoming)==len(outgoing)==1 and incoming<=set(old["reserves"])
                and set(players)<=set(allowed) and set(all_ids)==set(old["players"]+old["reserves"])
                and coach==old["coach"],"После фиксации возможна только замена на зарегистрированного запасного")
    require(coach is None or isinstance(coach,str) and pack["staff"].get(coach,{}).get("team")==team,
            "Тренер не принадлежит команде")
    core = event.get("invites",{}).get(team)
    if core:
        minimum = 3 if reason else event["rules"]["core"]
        require(len(set(players)&set(core)) >= minimum, "Не сохранено приглашённое ядро")
    for other in c["circuit"]["editions"].values():
        if conflicts(event,other):
            for tid, rows in other["registrations"].items():
                if tid != team and other["entries"].get(tid) in ("accepted","qualified","locked"):
                    latest=rows[-1]
                    require(set(all_ids).isdisjoint(latest["players"]+latest["reserves"]),
                            "Игрок заявлен за другую команду")
    row=dict(version=len(versions)+1,date=c["date"],players=list(players),reserves=list(reserves),
             coach=coach,reason=reason)
    event["registrations"].setdefault(team,[]).append(row)
    return row
