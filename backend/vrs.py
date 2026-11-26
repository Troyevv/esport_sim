"""Offline standings calculation against Valve's November 2026 model.

Inputs are classified series. A match carries both actual fives; a completed event
supplies the prize per participant, LAN status and final date. No club OVR enters here.
"""
from collections import Counter
from math import log, log10, pi, sqrt

from .database import day

MODEL="f8c55f250fdef796d708aa32814587932154fa04"


def calculate(matches, events, cutoff, countries, regions):
    end=day(cutoff)
    def age(date):
        return min(1,max(0,(180-(end-day(date)).days)/150))
    recent=sorted((m for m in matches if 0 <= (end-day(m["date"])).days <= 180
                   and events[m["event"]]["end"]<=cutoff and m["ranked"]
                   and all(len(f)==5 for f in m["fives"])),key=lambda m:m["date"],reverse=True)
    teams=[]
    games=[]
    for m in recent:
        sides=[]
        for org,five in zip(m["teams"],m["fives"],strict=True):
            players=set(five)
            idx=next((i for i,t in enumerate(teams) if len(players & t["base"])>=3),None)
            if idx is None:
                idx=len(teams)
                teams.append(dict(team=org,base=players,lineups=[],won=[],prizes={}))
            t=teams[idx]
            t["lineups"].append(five)
            t["prizes"].setdefault(m["event"],events[m["event"]]["payouts"].get(org,0))
            sides.append(idx)
        w=m["teams"].index(m["winner"])
        winner,loser=sides[w],sides[1-w]
        teams[winner]["won"].append((loser,m))
        games.append((winner,loser,m["date"]))
    if not teams:
        return []
    def top(values):
        return sum(sorted(values,reverse=True)[:10])
    for t in teams:
        network={}
        for opp,m in t["won"]:
            network.setdefault(opp,age(m["date"]))
        t["network"]=sum(network.values())
        t["lan"]=top(age(m["date"]) for _,m in t["won"] if events[m["event"]]["lan"])/10
        t["bounty"]=top(amount*age(events[e]["lastMatch"]) for e,amount in t["prizes"].items())
    for factor in ("network","lan","bounty"):
        reference=sorted((t[factor] for t in teams),reverse=True)[min(4,len(teams)-1)]
        # The published JS produces NaN without a nonzero fifth reference.
        # Such sparse windows have no usable standings.
        if not reference:
            return []
        for t in teams:
            t[factor+"Ratio"]=min(1,t[factor]/reference)
    def curve(value):
        return 1/(1+abs(log10(value))) if value>0 else 0
    for t in teams:
        opponents=[(teams[o],age(m["date"])*curve(max(1,min(events[m["event"]]["pool"],1000000))/1000000))
                   for o,m in t["won"]]
        t["seed"]=(curve(top(o["bountyRatio"]*weight for o,weight in opponents)/10)
                   +curve(t["bountyRatio"])+top(o["networkRatio"]*weight for o,weight in opponents)/10+t["lanRatio"])/4
    low=min(t["seed"] for t in teams)
    high=max(t["seed"] for t in teams)
    for t in teams:
        t["points"]=400+1600*((t["seed"]-low)/(high-low) if high!=low else .5)
    q=log(10)/400
    g=1/sqrt(1+3*(q*75/pi)**2)
    for winner,loser,date in sorted(games,key=lambda m:m[2]):
        a,b=teams[winner],teams[loser]
        expected=1/(1+10**(-g*(a["points"]-b["points"])/400))
        info=age(date)
        variance=1/(1/75**2+q*q*g*g*expected*(1-expected)*info**2)
        delta=q*variance*g*(1-expected)*info
        a["points"]+=delta
        b["points"]-=delta
    rows=[]
    regional=Counter()
    for t in sorted(teams,key=lambda t:-t["points"]):
        if len(t["lineups"])<5 or not t["network"]:
            continue
        last=t["lineups"][:10]
        counts=Counter(p for five in last for p in five)
        core=list(dict.fromkeys(p for five in last[:-1] for p in five if counts[p]>=5))[:5]
        totals=Counter(regions.get(countries.get(p)) for p in core if countries.get(p))
        priority=["Asia","Americas","Europe"]
        low=min((priority.index(r) for r in totals if r in priority),default=0)
        totals[priority[low]]+=totals.pop("Africa",0)
        region=max(reversed(priority),key=lambda r:totals[r])
        regional[region]+=1
        rows.append(dict(team=t["team"],core=core,points=int(t["points"]+.5),
                         rank=len(rows)+1,region=region,regional=regional[region]))
    return rows
