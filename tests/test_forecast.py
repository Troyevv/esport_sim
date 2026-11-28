from copy import deepcopy
from itertools import permutations
from statistics import mean

import pytest

from backend import forecast


@pytest.mark.parametrize("best", [1,3,5])
def test_prices_and_exact_scores_agree_before_and_after_picks(best):
    probs = {chr(97+i):.17+.11*i for i in range(7)}
    prior = dict(teams=["A","B"],day="2026-11-28",bestOf=best,mapProbabilities=probs)
    orders = list(permutations(probs,best))
    opening = forecast.market(prior)
    assert sum(opening["probability"]) == pytest.approx(1)
    assert sum(s["probability"] for s in opening["scores"]) == pytest.approx(1)
    assert opening["probability"][0] == pytest.approx(sum(s["probability"] for s in opening["scores"] if s["score"][0]>s["score"][1]))
    assert sum(1/n for n in opening["odds"]) == pytest.approx(1+forecast.MARGIN)
    assert sum(1/s["odds"] for s in opening["scores"]) == pytest.approx(1+forecast.MARGIN)
    assert mean(forecast.market(prior,o)["probability"][0] for o in orders) == pytest.approx(opening["probability"][0])
    assert min(forecast.market(prior,orders[0])["odds"]) > 1


def test_future_results_private_state_and_fixture_seed_have_no_influence():
    day = "2026-11-28"
    event = dict(id="upcoming",date=day,teams=["a","b"],mapId="de_nuke",seed=47)
    pack = dict(rosters={t:{"players":[t+str(i) for i in range(5)]} for t in event["teams"]},
                players={t+str(i):{"potential":88,"skills":{"aim":75}} for t in event["teams"] for i in range(5)})
    game = dict(teams={t:t for t in event["teams"]},date=day,history=[])
    before = forecast.opening(game,pack,event,day)
    assert before[1]["probability"] == [.5,.5]
    pack["players"]["b0"].update(potential=20,skills={"aim":99},morale=12)
    event["seed"] += 999
    history = dict(id="past",date=day,teams=["a","b"],score=[13,7],winnerTeamId="a",mapId="de_nuke")
    game["history"] += [dict(history,date="2026-11-29"),dict(history,id="upcoming"),dict(history,pcw=True)]
    assert forecast.opening(game,pack,event,day) == before
    game["history"].append(history)
    assert forecast.opening(game,pack,event,day)[1]["probability"][0] > .5


def test_saved_line_changes_on_veto_and_survives_replay():
    basis = dict(teams=["a","b"],day="2026-11-28",bestOf=1,mapProbabilities={"nuke":.3,"dust":.6})
    first = dict(forecast.market(basis), stage="opening")
    s = dict(forecastBasis=basis,forecasts=[first],stage="ready",order=[{"map":"dust"}],actions=[dict(kind="ban",map="nuke")])
    forecast.after_veto(s)
    restored=deepcopy(s)
    forecast.after_veto(restored)
    assert restored==s
    assert s["forecasts"][-1]["stage"]=="locked"
    assert s["forecasts"][-1]["probability"]==[.6,.4]
    assert forecast.calibration([{},dict(forecastScore=dict(version=forecast.VERSION,brier=.16))]) == dict(count=1,brier=.16)


def test_completed_career_report_preserves_preplay_line_and_calibration(tmp_path):
    from backend import career
    from backend.store import Store
    from tests.test_career import start
    store=Store(tmp_path/"profile.sqlite")
    start(store)
    c=store.read()["career"]
    event=next(e for e in c["queue"] if e["kind"]=="match" and c["team"] in e["teams"])
    c["queue"]=[event]
    c["date"]=event["date"]
    pack=store.careers.pack(c["source"])
    expected=deepcopy(event["forecasts"])
    game=career.initial(pack,c,event,detailed=False)
    report=career.simulate(game)
    assert report["forecasts"][:len(expected)] == expected
    assert report["forecasts"][-1]["stage"] == ("locked" if event.get("bestOf") else "opening")
    store.careers.record(c,report)
    archived=store.careers.historical_report(c,c["history"][-1])
    assert archived["forecasts"] == report["forecasts"]
    measured=forecast.calibration(c["history"])
    probability=report["forecasts"][-1]["probability"][0]
    assert measured["count"]==1
    assert measured["brier"]==pytest.approx((probability-int(report["winnerTeamId"]==event["teams"][0]))**2)
