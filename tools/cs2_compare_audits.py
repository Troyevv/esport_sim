"""Compare frozen professional rounds with paired and held-out BO1 cohorts (offline QA only)."""

import argparse
import collections
import json
from pathlib import Path
import random
import statistics as st

import duckdb


def professional_rounds(directory):
    db = duckdb.connect()
    for name in ["maps", "rounds", "team_round_economy"]:
        db.read_parquet(str(directory / ("full_" + name + ".parquet"))).create_view(
            name
        )
    return db.execute("""select r.map_name,r.map_uid,r.round_num,r.winner_side,r.end_reason,r.bomb_planted,
 (r.end_tick-r.freeze_end_tick)/64.0,t.team_current_equip_value, CT.team_current_equip_value,m.hltv_stars, t.team_spend, ct.team_spend,
 (r.bomb_plant_tick-r.freeze_end_tick)/64.0
 from rounds r join maps m using(map_uid)
 join team_round_economy t on r.map_uid=t.map_uid and r.round_num=t.round_num and t.side='t'
 join team_round_economy ct on r.map_uid=ct.map_uid and r.round_num=ct.round_num and ct.side='ct'
 where m.structural_qc_pass and m.analysis_eligible_v1 and r.map_name != 'de_overpass'
 order by r.map_name,r.map_uid,r.round_num""").fetchall()


maps = [
    "de_ancient",
    "de_anubis",
    "de_cache",
    "de_dust2",
    "de_inferno",
    "de_mirage",
    "de_nuke",
    "de_train",
    "de_vertigo",
]
rus = {
    "Устранение": "kill",
    "Время": "timeout",
    "Взрыв C4": "explode",
    "Обезвреживание": "defuse",
}
en = {
    "ct_killed": "kill",
    "t_killed": "kill",
    "time_ran_out": "timeout",
    "bomb_exploded": "explode",
    "bomb_defused": "defuse",
}


def rates(rows):
    n = len(rows)
    if not n:
        return {}
    w = sum(r["side"] == "T" for r in rows)
    plants = sum(r["plant"] for r in rows)
    reasons = collections.Counter(r["reason"] for r in rows)
    econ = []
    for t, ct in [(True, True), (True, False), (False, True), (False, False)]:
        g = [r for r in rows if (r["T"] >= 18000) == t and (r["CT"] >= 18000) == ct]
        econ.append(
            (
                len(g),
                round(100 * sum(r["side"] == "T" for r in g) / len(g), 1)
                if g
                else None,
            )
        )
    return dict(
        n=n,
        t=round(w * 100 / n, 1),
        ct=round((n - w) * 100 / n, 1),
        plant=round(plants * 100 / n, 1),
        defuses=round(reasons["defuse"] * 100 / plants, 1) if plants else None,
        reason=[reasons[k] for k in ["kill", "timeout", "explode", "defuse"]],
        duration=round(st.median(r["duration"] for r in rows), 1),
        eco=econ,
    )


def sim(folder, n):
    matches = [
        json.loads(s) for s in (folder / (n + ".jsonl")).read_text().splitlines()
    ]
    rows = [r for g in matches for r in g["rounds"]]
    data = [
        dict(
            side=r["side"],
            reason=rus[r["reason"]],
            plant="plant" in r,
            duration=r["duration"] / 10,
            **r["equip"],
        )
        for r in rows
    ]
    report = rates(data)
    plants = sum("plant" in r for r in rows)
    re = sum(r["retake"] for r in rows)
    report.update(
        games=len(matches),
        plantSeconds=round(st.median(r["plant"] / 10 for r in rows if "plant" in r), 1)
        if plants
        else None,
        medianSec=round(st.median(g["seconds"] for g in matches), 2),
        save=round(
            sum(r["side"] == "T" and r["survivingCT"] > 0 for r in rows)
            * 100
            / max(1, sum(r["side"] == "T" for r in rows)),
            1,
        ),
        intendedSaves=sum(r["saves"] for r in rows),
        retakes=re,
        retakeWins=sum(r["retake"] and r["reason"] == "Обезвреживание" for r in rows),
        ctUtility=round(
            sum(sum(r["utility"]["CT"].values()) for r in rows) / len(rows), 2
        ),
        tUtility=round(
            sum(sum(r["utility"]["T"].values()) for r in rows) / len(rows), 2
        ),
        arrivals=round(st.median(v / 10 for r in rows for v in r["holdsReached"]), 1),
        contact=round(
            st.median(r["contact"] / 10 for r in rows if r["contact"] is not None), 1
        ),
        rotate=sum(r["rotations"] for r in rows),
        utility=collections.Counter(),
    )
    for r in rows:
        for team in ["CT", "T"]:
            report["utility"].update(r["utility"][team])
    return report


def professional(pro, n):
    g = [r for r in pro if r[0] == n]
    rr = [
        dict(
            side=a[3].upper(),
            reason=en[a[4]],
            plant=a[5],
            duration=a[6],
            T=a[7],
            CT=a[8],
        )
        for a in g
    ]
    if not g:
        return {}
    res = rates(rr)
    res.update(
        games=len({x[1] for x in g}),
        purchases=st.median(spend for r in g for spend in r[10:12]),
        zero=round(
            100 * sum(not spend for r in g for spend in r[10:12]) / (2 * len(g)), 1
        ),
        plantSeconds=round(st.median(r[12] for r in g if r[5]), 1),
        stars=len({x[1] for x in g if x[9] > 0}),
        starT=rates([r for r, x in zip(rr, g) if x[9] > 0]).get("t"),
    )
    return res


def paired_delta(old, new):
    # Resample complete roster+seed pairs, preserving both starting sides.
    if len(old) != len(new) or len(old) % 2:
        raise ValueError("Incomplete mirror comparison")
    pairs = []
    for i in range(0, len(old), 2):
        totals = []
        for group in [old[i : i + 2], new[i : i + 2]]:
            if (
                group[0]["seed"] != group[1]["seed"]
                or group[0]["teams"] != group[1]["teams"][::-1]
            ):
                raise ValueError("Pair is missing its reverse fixture")
            rows = group[0]["rounds"] + group[1]["rounds"]
            totals.extend([sum(r["side"] == "T" for r in rows), len(rows)])
        if any(
            old[j]["teams"] != new[j]["teams"] or old[j]["seed"] != new[j]["seed"]
            for j in (i, i + 1)
        ):
            raise ValueError("Lineup or seed changed between versions")
        pairs.append(totals)
    rng = random.Random(4121)
    changes = []
    for _ in range(2000):
        a, b, c, d = map(sum, zip(*rng.choices(pairs, k=len(pairs))))
        changes.append(100 * (c / d - a / b))
    changes.sort()
    return [round(changes[49], 1), round(changes[1949], 1)]


def raw_professional(files):
    data = {}
    for f in files:
        games = json.loads(f.read_bytes())
        if not isinstance(games, list) or not games or "rounds" not in games[0]:
            continue
        rows = [r for g in games for r in g["rounds"]]
        utilities = collections.Counter()
        for r in rows:
            utilities.update(r["grenades"])
        equip_rows = []
        for r in rows:
            initial = r["radar"].get("0", [])
            if len(initial) == 10:
                equip_rows.append(
                    dict(
                        T=sum(p[5] for p in initial if p[0] == 2),
                        CT=sum(p[5] for p in initial if p[0] == 3),
                        side=r["winner"].upper(),
                        reason=en[r["reason"]],
                        plant=r["plant"],
                        duration=r["duration"],
                    )
                )
        plants = [r for r in rows if r["plant"]]
        plant_times = [r["plantSeconds"] for r in plants if r.get("plantSeconds") is not None]
        touches_known = bool(plants) and all(r.get("touched") is not None for r in plants)
        data[games[0]["map"]] = dict(
            plantSeconds=round(st.median(plant_times), 1) if plant_times else None,
            touched=sum(r["touched"] for r in plants) if touches_known else None,
            plantedRounds=len(plants),
            eco=rates(equip_rows).get("eco", []),
            games=len(games),
            n=len(rows),
            t=round(100 * sum(r["winner"] == "t" for r in rows) / len(rows), 1),
            plant=round(100 * sum(r["plant"] for r in rows) / len(rows), 1),
            defuses=round(
                100
                * sum(r["reason"] == "bomb_defused" for r in rows)
                / max(1, sum(r["plant"] for r in rows)),
                1,
            ),
            reason=[
                sum(en.get(r["reason"]) == reason for r in rows)
                for reason in ("kill", "timeout", "explode", "defuse")
            ],
            wait=round(st.median(r["duration"] for r in rows), 1),
            utility=utilities,
            saved=round(
                100
                * sum(r["winner"] == "t" and r["survivingCT"] > 0 for r in rows)
                / max(1, sum(r["winner"] == "t" for r in rows)),
                1,
            ),
        )
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("before", "after", "reference", "out"):
        p.add_argument("--" + n, required=True, type=Path)
    p.add_argument("--demos", type=Path, nargs="*", default=[])
    args = p.parse_args()
    pro = professional_rounds(args.reference)
    raw = raw_professional(args.demos)
    result = {}
    for name in maps:
        by_map = dict(pro=professional(pro, name), raw=raw.get(name, {}))
        for sample in ("paired", "independent"):
            cohorts = []
            for root, label in ((args.before, "before"), (args.after, "after")):
                path = root / sample / (name + ".jsonl")
                runs = [json.loads(line) for line in path.read_text().splitlines()]
                cohorts.append(runs)
                stats = sim(root / sample, name)
                if label == "after":
                    accounts = [
                        e
                        for g in runs
                        for r in g["rounds"]
                        for e in r["economy"].values()
                    ]
                    stats.update(
                        scenarios=collections.Counter(e["scenario"] for e in accounts),
                        purchases=st.median(e["spend"] for e in accounts),
                        pocket=st.median(e["pocket"] for e in accounts),
                        zero=round(
                            100 * sum(not e["spend"] for e in accounts) / len(accounts),
                            1,
                        ),
                        drops=sum(e["drops"] for e in accounts),
                        noSpendViolations=sum(
                            e["spend"] > 0 and e["budget"] == "Эко" for e in accounts
                        ),
                    )
                by_map[label + "-" + sample] = stats
            by_map["delta95-" + sample] = paired_delta(*cohorts)
        result[name] = by_map
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
