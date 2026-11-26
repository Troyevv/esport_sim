"""Competition calendar, registration and stage advancement inside the career transaction."""
import hashlib
from copy import deepcopy

from . import competition_stages as stages, registrations
from .competition_catalog import offset, season, seed_data
from .database import day, require


def clock(c, date, title):
    if not any(e["date"]==date and e["kind"]=="review" for e in c["queue"]):
        c["queue"].append(dict(kind="review",id="day-"+date,date=date,teams=[],title=title))


def order(c):
    c["queue"].sort(key=lambda e:(e["date"], e["kind"]=="match", c["team"] in e["teams"], e["id"]))


def notice(c, event, title, body):
    c["milestones"].append(dict(date=c["date"],title=event["title"]+" · "+title,
                                body=body,matches=None))


def snapshot(c, date):
    dates = {**seed_data()["snapshots"], **c["circuit"]["snapshots"]}
    key = max((key for key in dates if key <= date),default=None)
    return (key,dates[key]) if key else (None,[])


def rank(c, date, pack):
    key, rows = snapshot(c,date)
    return key,{r["team"]:r for r in rows if r.get("team") in c["teams"]
                and len(set(r["core"]) & set(pack["rosters"][c["teams"][r["team"]]]["players"]))>=3}


def init(c, pack):
    c["circuit"] = dict(version=1,editions={},bench={},snapshots={},awards={})
    for row in seed_data()["major"]:
        tid = row["team"]
        if tid in c["teams"]:
            main = pack["rosters"][c["teams"][tid]]["players"]
            c["circuit"]["bench"][tid] = [p for p in row["players"]+row["reserves"] if p not in main]
    add_season(c,pack,int(c["date"][:4]))


def add_season(c, pack, year):
    events = c["circuit"]["editions"]
    for event in season(year):
        events[event["id"]] = event
        if event["admission"]=="invitation" and not event["simulated"]:
            import_major(c,event)
        for key, title in (("opens","Открытие регистрации"),("lock","Фиксация составов"),("start","Старт турнира")):
            if event[key]>c["date"]:
                clock(c,event[key],title)
        reminder = offset(event["lock"],-1)
        if reminder>c["date"]:
            clock(c,reminder,"Завтра завершается регистрация")
    process_day(c,pack)
    clock(c,f"{year+1}-01-01","Новый сезон")
    order(c)


def import_major(c,event):
    rows=seed_data()["major"]
    event["invites"]={}
    for row in rows:
        tid=row["team"]
        require(tid in c["teams"],"В базе отсутствует участник Singapore Major")
        event["entries"][tid]="locked"
        event["invites"][tid]=row["players"].copy()
        event["registrations"][tid]=[dict(version=1,date=event["lock"],reason=None,
            players=row["players"].copy(),reserves=row["reserves"].copy(),coach=row["coach"])]
    ids=[r["team"] for r in rows]
    event["direct"]={"0":ids[16:],"1":ids[8:16],"2":ids[:8]}
    event.update(status="playing",snapshot="2026-11-02")
    draw=stages.draw("swiss",ids[16:],8)
    draw["games"].clear()
    # Series results on 24 November, before the shipped edition starts.
    # Values refer to the published 32-team participant manifest, winning team first.
    rounds=[[(26,18,6),(31,23,11),(16,24,10),(22,28,1),(17,25,3),(27,19,9),(29,20,7),(21,30,6)],
            [(26,21,11),(22,27,8),(29,17,9),(16,31,10),(20,25,8),(18,30,3),(24,23,8),(19,28,3)]]
    for rnd, matches in enumerate(rounds):
        for winner,loser,score in matches:
            teams=[ids[winner],ids[loser]]
            i=stages.game(draw,teams,rnd,f"Раунд {rnd+1}")
            draw["games"][i].update(winner=teams[0],loser=teams[1],historical=True,score=[13,score],date="2026-11-24")
    draw["round"]=2
    stages.swiss_round(draw)
    event["draws"]=[[draw]]
    schedule_draw(c,event)


def selected(c,event,pack):
    return [t for t in c["teams"] if event["region"] in ("Global",pack["teams"][t]["region"])]


def issue_invites(c,event,pack):
    stamp, ranks = rank(c,event["opens"],pack)
    event["snapshot"]=stamp
    event["invites"]={}
    # Singapore allocation following Cologne: Stage 3 EU 6/AM 2, Stage 2
    # EU 6/AM 1/Asia 1; Stage 1 EU 6/AM 6/Asia 4.
    remaining = sorted(ranks, key=lambda t:ranks[t]["rank"])
    for stage,slots in [(2,(6,2,0)),(1,(6,1,1)),(0,(6,6,4))]:
        entries=[]
        for region,count in zip(("Europe","Americas","Asia"),slots,strict=True):
            group=[t for t in remaining if ranks[t]["region"]==region and len(ranks[t]["core"])==5][:count]
            for tid in group:
                remaining.remove(tid)
                entries.append(tid)
                event["invites"][tid]=ranks[tid]["core"]
                event["entries"][tid]="invited"
        event["direct"][str(stage)]=sorted(entries,key=lambda t:ranks[t]["rank"])


def process_day(c,pack):
    events=c["circuit"]["editions"]
    # Higher prestige and then larger purses get the first decision on conflicting dates.
    for event in sorted(events.values(),key=lambda e:(e["prestige"],-sum(e["prizes"]),e["id"])):
        if event["status"]!="registration" or c["date"]<event["opens"]:
            continue
        if event["admission"]=="qualified":
            continue
        if c["date"]<event["lock"]:
            if event["admission"]=="invitation" and "invites" not in event:
                issue_invites(c,event,pack)
            if not event.get("announced"):
                event["announced"]=True
                if c["team"] in selected(c,event,pack) and (event["admission"]!="invitation"
                        or c["team"] in event["invites"]):
                    notice(c,event,"Приглашение" if event["admission"]=="invitation" else "Открыта регистрация",
                           "Подтвердите участие и подайте состав до "+event["lock"]+".")
            if offset(c["date"],1)==event["lock"] and event["entries"].get(c["team"])=="accepted":
                notice(c,event,"Дедлайн завтра","Проверьте пятёрку, запасных и тренера.")
            auto_register(c,event,pack)
        else:
            lock(c,event,pack)
    order(c)


def auto_register(c,event,pack):
    regional_ranks = rank(c,c["date"],pack)[1] if event["admission"]=="rankedOpen" else {}
    for team in selected(c,event,pack):
        if team==c["team"] or event["entries"].get(team) not in (None,"invited"):
            continue
        if event["admission"]=="invitation" and team not in event["invites"]:
            continue
        if event["admission"]=="rankedOpen" and team not in regional_ranks:
            continue
        if event["admission"]=="open" and pack["teams"][team]["tier"]==1:
            continue
        if any(e.get("feeds")==event.get("feeds") and e is not event
               and team in e.get("advanced",[]) for e in c["circuit"]["editions"].values()) and event.get("feeds"):
            continue
        try:
            registrations.signup(c,event,team,pack)
        except ValueError:
            continue
        players=pack["rosters"][c["teams"][team]]["players"]
        reserve=c["circuit"]["bench"].get(team,[])[:event["rules"]["reserves"]]
        coach=next((sid for sid,s in pack["staff"].items() if s["team"]==team),None)
        try:
            registrations.submit(c,event,team,pack,players,reserve,coach)
        except ValueError as exc:
            event["entries"][team]="declined"
            event.setdefault("reasons",{})[team]=str(exc)


def lock(c,event,pack):
    eligible=[]
    for team,state in event["entries"].items():
        if state not in ("accepted","invited","qualified"):
            continue
        versions=event["registrations"].get(team)
        if not versions or not set(versions[-1]["players"])<=set(registrations.available(c,team,pack)):
            event["entries"][team]="missed"
            if team==c["team"]:
                notice(c,event,"Пропущена регистрация","На момент фиксации нет допустимой пятёрки.")
        else:
            eligible.append(team)
    stamp,ranks=rank(c,c["date"],pack)
    event["seedSnapshot"]=stamp
    eligible.sort(key=lambda t:(ranks[t]["rank"] if t in ranks else 10**6,t))
    # Open CCT slots are limited at signup; ECL selects ranked applications at lock.
    if event["admission"]=="rankedOpen":
        eligible=[t for t in eligible if t in ranks]
    eligible=eligible[:event["capacity"]]
    field=set(eligible)
    for team,status in event["entries"].items():
        if status in ("accepted","qualified"):
            event["entries"][team]="locked" if team in field else "notSelected"
    if event["admission"]=="invitation":
        for key,teams in event["direct"].items():
            event["direct"][key]=[t for t in teams if t in field]
        eligible=event["direct"]["0"]
    if len(eligible)<2 or event["stages"][0]["format"]=="swiss" and len(eligible)!=16:
        event.update(status="cancelled",reason="Недостаточно допущенных команд")
        return
    event["status"]="playing"
    begin(c,event,eligible)


def begin(c,event,field):
    spec=event["stages"][len(event["draws"])]
    if spec["format"]=="gsl":
        groups=[field[i::4] for i in range(4)]
        draws=[]
        for group in groups:
            if len(group)<2:
                continue
            # Winners' match qualifies first; its loser faces the elimination match winner.
            d=stages.draw("single",group)
            upper_final=d["outputs"][0][1]
            if len(group)==4:
                elim=stages.game(d,[("loser",0),("loser",1)],1,"Матч на вылет")
                decider=stages.game(d,[("loser",upper_final),("winner",elim)],2,"Решающий матч")
                d["outputs"].append(("winner",decider))
            draws.append(d)
    else:
        draws=[stages.draw(spec["format"],field,spec["advance"],bronze=spec.get("bronze",False))]
    event["draws"].append(draws)
    if c["team"] in field:
        notice(c,event,"Опубликована сетка",spec["name"])
    schedule_draw(c,event)


def schedule_draw(c,event):
    index=len(event["draws"])-1
    spec=event["stages"][index]
    draws=event["draws"][index]
    promoted=[]
    for group,draw in enumerate(draws):
        ready=stages.ready(draw)
        output=stages.finish_round(draw)
        if output is not None:
            promoted.extend(output)
        elif not ready:
            ready=stages.ready(draw)
        for n,teams in ready:
            row=draw["games"][n]
            fixture=f"{event['id']}.{index}.{group}.{n}"
            duration=(day(spec["end"])-day(spec["start"])).days
            max_round=max(g["round"] for g in draw["games"])
            delta=(spec["roundDays"][row["round"]] if "roundDays" in spec else
                   round(duration*row["round"]/max(1,max_round)))
            when=max(c["date"],offset(spec["start"],delta))
            best=3 if row.get("deciding") else spec["bestOf"]
            if draw.get("outputs")==[("winner",n)] or draw.get("outputs")==[["winner",n]]:
                best=spec.get("finalBO",best)
            row.update(fixture=fixture,date=when)
            c["queue"].append(dict(kind="match",id=fixture,date=when,teams=teams,edition=event["id"],
                title=event["title"],stage=index,group=group,game=n,bestOf=best,
                seed=int.from_bytes(hashlib.sha256(fixture.encode()).digest()[:4],"big")>>1))
    order(c)
    if any(any("winner" not in g for g in draw["games"]) for draw in draws):
        return
    if index+1<len(event["stages"]):
        begin(c,event,event["direct"].get(str(index+1),[])+promoted)
    else:
        finish(c,event,promoted)


def finish(c,event,promoted):
    event.update(status="finished",advanced=promoted)
    if "feeds" in event:
        target=c["circuit"]["editions"][event["feeds"]]
        for team in promoted:
            target["entries"][team]="qualified"
            target["registrations"][team]=deepcopy(event["registrations"][team])
            for sibling in c["circuit"]["editions"].values():
                if sibling is not event and sibling.get("feeds")==target["id"] and sibling["status"]=="registration":
                    if team in sibling["entries"]:
                        sibling["entries"][team]="qualifiedElsewhere"
            if team==c["team"]:
                notice(c,target,"Квалификация пройдена","Заявка перенесена из открытого отбора.")
        if all(e["status"] in ("finished","cancelled") for e in c["circuit"]["editions"].values()
               if e.get("feeds")==target["id"]):
            clock(c,target["lock"],"Фиксация состава основного этапа")
        return
    placements=list(promoted)
    for draws in reversed(event["draws"]):
        for draw in draws:
            if draw["format"]=="swiss":
                placements.extend(r["team"] for r in stages.table(draw) if r["team"] not in placements)
                continue
            games=list(reversed(draw["games"]))
            for g in games:
                if g["label"]=="За третье место":
                    continue
                loser=g.get("loser")
                if loser and loser not in placements:
                    placements.append(loser)
            bronze=next((g for g in games if g["label"]=="За третье место"),None)
            if bronze:
                placements[2:4]=[bronze["winner"],bronze["loser"]]
    event["placements"]=placements
    event["payouts"]={t:p for t,p in zip(placements,event["prizes"])}
    c["circuit"]["awards"][event["id"]]=event["payouts"].copy()
    if event["stats"]:
        event["mvp"]=max(event["stats"],key=lambda p:(event["stats"][p]["damage"]/event["stats"][p]["rounds"],
                                                        event["stats"][p]["k"],p))
    if c["team"] in placements:
        notice(c,event,"Турнир завершён",f"Место: {placements.index(c['team'])+1}.")


def completed(c,e,report):
    event=c["circuit"]["editions"][e["edition"]]
    draw=event["draws"][e["stage"]][e["group"]]
    winner=report["winnerTeamId"]
    stages.record(draw,e["game"],winner,next(t for t in e["teams"] if t!=winner))
    draw["games"][e["game"]]["score"]=report["score"]
    for row in report["stats"]:
        target=event["stats"].setdefault(row["player"],dict(team=row["teamId"],name=row["name"],rounds=0,k=0,d=0,a=0,damage=0))
        for key in ("k","d","a","damage"):
            target[key]+=row[key]
        target["rounds"]+=len(report["rounds"])
    schedule_draw(c,event)


def tick(c,pack):
    live=c["circuit"].get("live")
    if live and live["completeWindow"] and day(c["date"]).weekday()==0 and day(c["date"]).day<=7:
        c["circuit"]["snapshots"].setdefault(c["date"],deepcopy(live["rows"]))
    if c["date"].endswith("-01-01"):
        add_season(c,pack,int(c["date"][:4]))
    else:
        for event in c["circuit"]["editions"].values():
            if event["admission"]=="qualified" and event["status"]=="registration" and event["lock"]<=c["date"]:
                lock(c,event,pack)
        process_day(c,pack)


def publish(c,pack):
    from . import vrs
    from .competition_catalog import DATA
    import json
    events={e["id"]:dict(end=e["end"],lastMatch=max((g.get("date",e["end"]) for d in e["draws"] for group in d
                for g in group["games"] if "fixture" in g),default=e["end"]),
            lan=e["region"]=="Global",pool=sum(e["prizes"]),payouts=e.get("payouts",{}))
            for e in c["circuit"]["editions"].values() if e["status"]=="finished"}
    matches=[]
    for e in c["history"]:
        if e.get("edition") not in events:
            continue
        event=c["circuit"]["editions"][e["edition"]]
        matches.append(dict(date=e["date"],event=e["edition"],teams=e["teams"],winner=e["winnerTeamId"],
                            ranked=event["admission"]!="open",
                            fives=[event["registrations"][t][e["rosterVersions"][t]-1]["players"] for t in e["teams"]]))
    rows=vrs.calculate(matches,events,c["date"],{pid:p["nationality"] for pid,p in pack["players"].items()},
                       json.loads((DATA/"vrs-regions.json").read_bytes()))
    for r in rows:
        r["name"]=pack["teams"][r["team"]]["name"]
        r["nicks"]=[pack["players"][p]["name"] for p in r["core"]]
    if rows:
        c["circuit"]["live"]={"date":c["date"],"rows":rows,
                             "completeWindow":(day(c["date"])-day(c["start"])).days>=180}
