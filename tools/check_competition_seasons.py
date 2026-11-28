"""Extended calendar regression with test reports. For the actual engine run check_competition_lifecycle."""

import gzip
import json
from time import monotonic

from backend import career, competition_scene, competitions, database


def check():
    start = monotonic()
    pack = competition_scene.extend(
        json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    )
    team = next(t for t, v in pack["teams"].items() if v["name"] == "SINNERS Esports")
    c = career.create(pack, dict(team=team, name="Тренер", scope="full", mode="owner"))
    ids = set()
    played = {}
    while c["queue"][0]["date"] < "2028-01-01":
        fixture = c["queue"][0]
        if fixture.get("edition") and competitions.fixture_conflicts(c, fixture):
            c["date"] = fixture["date"]
            competitions.settle_fixture_conflicts(c, fixture, pack)
            if c.get("error"):
                # This unattended acceptance career chooses the higher-priority
                # tournament when production asks its manager for a decision.
                others = competitions.fixture_conflicts(c, fixture)
                competing = [c["circuit"]["editions"][f["edition"]] for f in [fixture,*others] if team in f["teams"]]
                assert len(competing) >= 2, c["error"]
                lost = max(competing, key=lambda e: competitions.priority_for(e, team))
                competitions.leave(c, lost, team, pack, "Приоритет календаря в контрольном сезоне")
                c.pop("error", None)
            continue
        c["queue"].pop(0)
        assert fixture["date"] >= c["date"] and fixture["id"] not in ids
        ids.add(fixture["id"])
        c["date"] = fixture["date"]
        if fixture["kind"] == "review":
            competitions.tick(c, pack)
            continue
        edition = c["circuit"]["editions"][fixture["edition"]]
        teams = fixture["teams"]
        winner = teams[fixture["seed"] % 2]
        versions = {}
        for t in teams:
            registered = edition["registrations"][t][-1]
            assert len(set(registered["players"])) == 5
            assert edition["entries"][t] == "locked"
            key = (fixture["date"], t)
            assert played.setdefault(key, edition["id"]) == edition["id"], (
                key,
                played[key],
                edition["id"],
            )
            versions[t] = registered["version"]
        c["history"].append(
            dict(**fixture, rosterVersions=versions, winnerTeamId=winner)
        )
        competitions.completed(
            c,
            fixture,
            dict(
                winnerTeamId=winner,
                score=[int(t == winner) for t in teams],
                stats=[],
                rounds=[],
            ),
        )
        if edition["status"] == "finished":
            competitions.publish(c, pack)
    calendar = c["circuit"]["editions"]
    completed = [e for e in calendar.values() if e["status"] == "finished"]
    for eid in [
        "pgl-major-2026",
        "cct-europe-2026",
        "draculan-2026",
        "iem-krakow-2027",
        "blast-open-2027",
        "fire-major-2027",
        "pw-major-2027",
    ]:
        assert calendar[eid]["status"] == "finished", (eid, calendar[eid].get("reason"))
    for e in completed:
        assert len(e["placements"]) == len(set(e["placements"]))
        if e.get("payouts"):
            assert e["payouts"] == c["circuit"]["awards"][e["id"]]
    assert len(c["circuit"]["snapshots"]) == 13
    print(
        f"{len(c['history'])} test series, {len(completed)} completed events, 13 monthly snapshots in {monotonic() - start:.1f}s"
    )


if __name__ == "__main__":
    check()
