"""Virtual prices from information published by the forecast date."""
from functools import lru_cache
from math import exp, log
from statistics import mean

from . import competitions, veto

VERSION = "public-series.1"
MARGIN = .05


def inputs(career, pack, event, day):
    teams = event["teams"]
    edition = career.get("circuit", {}).get("editions", {}).get(event.get("edition"), {})
    pool = (edition.get("rules") or career.get("seriesProfile") or veto.REGULATION)["pool"] if event.get("bestOf") else [event.get("mapId") or "depo"]
    history = [h for h in career["history"] if h.get("winnerTeamId") and not h.get("pcw")
               and h["date"] <= day and h["id"] != event["id"] and any(t in h["teams"] for t in teams)]
    evidence = veto.evidence(pool, teams, history, day)
    publication, rankings = competitions.snapshot(career, day) if "circuit" in career else (None, [])
    clubs = {}
    form = {}
    for team in teams:
        entries = [r for r in edition.get("registrations", {}).get(team, []) if r["date"] <= day]
        players = entries[-1]["players"] if entries else pack["rosters"][career["teams"][team]]["players"]
        rank = next((r for r in rankings if r.get("team") == team and len(set(players).intersection(r["core"])) >= 3), None)
        recent = [h for h in reversed(history) if team in h["teams"]][:10]
        sample = []
        for pid in players:
            player = pack["players"][pid]
            rating = player.get("performance")
            source = pack.get("origins", {}).get(player.get("fields", {}).get("performance", player.get("origin")))
            if rating and source and source["status"] == "confirmed" and source["date"] <= day:
                sample.append(dict(player=pid, rating=rating["rating"], maps=rating["maps"], source=source["date"]))
        clubs[team] = dict(players=list(players), version=entries[-1]["version"] if entries else None,
                           rank=rank["rank"] if rank else None, publicRatings=sample, points=rank["points"] if rank else None,
                           retained=len(set(players).intersection(rank["core"])) if rank else None,
                           recent=[{k:h.get(k) for k in ("id","date","teams","winnerTeamId","score")} for h in recent])
        form[team] = (sum(h["winnerTeamId"] == team for h in recent)+3)/(len(recent)+6)
    a,b = teams
    head = [h for h in reversed(history) if set(h["teams"]) == set(teams)][:10]
    head_rate = (sum(h["winnerTeamId"] == a for h in head)+4)/(len(head)+8)
    logit = lambda p: log(p/(1-p))
    strength = .35*(logit(form[a])-logit(form[b])) + .25*logit(head_rate)
    if all(clubs[t]["points"] is not None for t in teams):
        continuity = min(clubs[t]["retained"] for t in teams)/5
        strength += continuity * (clubs[a]["points"]-clubs[b]["points"])/600
    if all(clubs[t]["publicRatings"] for t in teams):
        def rating(t):
            return mean((p["rating"]-1)*min(1,p["maps"]/20) for p in clubs[t]["publicRatings"])
        strength += .7*(rating(a)-rating(b))
    probabilities = {}
    for m in pool:
        rates = [(evidence[t][m]["weightedWins"]+3)/(evidence[t][m]["weight"]+6) for t in teams]
        odds = max(-3,min(3,strength+.55*(logit(rates[0])-logit(rates[1]))))
        probabilities[m] = 1/(1+exp(-odds))
    return dict(teams=teams, day=day, bestOf=event.get("bestOf",1), publication=publication, clubs=clubs,
                evidence=evidence, h2h=[{k:h.get(k) for k in ("id","date","teams","score","winnerTeamId")} for h in head],
                mapProbabilities=probabilities)


def market(prior, order=(), unavailable=()):
    """Known picks occupy fixed slots. Average unseen maps without replacement."""
    pool = prior["mapProbabilities"]
    best = prior["bestOf"]
    target = best//2+1
    pending = tuple(m for m in pool if m not in order and m not in unavailable)
    @lru_cache(None)
    def outcomes(a,b,maps):
        if a == target or b == target:
            return {(a,b): 1.0}
        slot = a+b
        choices = (order[slot],) if slot < len(order) else maps
        result = {}
        for m in choices:
            remaining = tuple(k for k in maps if k != m)
            for wa,wb,p in ((a+1,b,pool[m]),(a,b+1,1-pool[m])):
                for score,tail in outcomes(wa,wb,remaining).items():
                    result[score] = result.get(score,0) + p*tail/len(choices)
        return result
    scores = outcomes(0,0,pending)
    pa = sum(p for (a,b),p in scores.items() if a>b)
    def price(p, count):
        return 1/(p + MARGIN*(1-p)/(count-1))
    return dict(version=VERSION, date=prior["day"], bestOf=best, teams=list(prior["teams"]),
                order=list(order), bans=list(unavailable), margin=MARGIN, probability=[pa,1-pa],
                odds=[price(pa,2),price(1-pa,2)], scores=[
                    dict(score=[a,b], probability=p, odds=price(p,len(scores))) for (a,b),p in sorted(scores.items())])


def after_veto(series):
    if "forecastBasis" not in series:
        return
    order = [r["map"] for r in series["order"]]
    bans = [r["map"] for r in series["actions"] if r["kind"] == "ban"]
    quotes = series["forecasts"]
    if not series["actions"]:
        return
    stage = "locked" if series["stage"] == "ready" else "veto"
    if quotes[-1]["order"] == order and quotes[-1]["bans"] == bans and quotes[-1].get("stage") == stage:
        return
    quote = market(series["forecastBasis"],order,bans)
    quote.update(stage=stage, move=len(series["actions"]))
    quotes.append(quote)


def calibration(history):
    """One pre-play prediction per fixture prevents overweighting series with more veto steps."""
    samples = [h for h in history if h.get("forecastScore",{}).get("version") == VERSION]
    return dict(count=len(samples), brier=mean(h["forecastScore"]["brier"] for h in samples) if samples else None)


def opening(career, pack, event, day):
    public = inputs(career,pack,event,day)
    quote = market(public)
    quote.update(stage="opening", rosters={t:c["players"] for t,c in public["clubs"].items()},
                 publication=public["publication"])
    return public, quote


def remember(quotes, quote):
    previous = quotes[-1] if quotes else {}
    if any(previous.get(key) != value for key,value in quote.items() if key != "date"):
        quotes.append(quote)


def note_upcoming(career, pack):
    fixture = next((e for e in career["queue"] if e["kind"] == "match" and not e.get("pcw") and career["team"] in e["teams"]), None)
    if fixture:
        _, quote = opening(career,pack,fixture,career["date"])
        remember(fixture.setdefault("forecasts",[]),quote)
