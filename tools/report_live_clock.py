"""Reduce a Chromium/ASGI 60-second capture. All wall timestamps share the local host."""

import argparse
import json
from bisect import bisect_left, bisect_right
from math import dist
from pathlib import Path


def nearest_quantile(values, q):
    return round(sorted(values)[round((len(values) - 1) * q)], 2)


def summarize(folder):
    b = json.loads((folder / "browser.json").read_bytes())
    commits = [
        (s * 1000, tick, cost * 1000)
        for s, tick, cost in (
            json.loads(line)
            for line in (folder / "commit.jsonl").read_text().splitlines()
        )
    ]
    packets, renders = b["packets"], b["renders"]
    ct, ticks, _ = zip(*commits)
    pt, rt = [p[0] for p in packets], [r[0] for r in renders]
    lo, hi = b["start"], b["start"] + 60000

    def ix(seq, t):
        return bisect_right(seq, t) - 1

    i, j = ix(ct, lo), ix(ct, hi)
    f, l = ix(pt, lo), ix(pt, hi)
    server_time = dict((tick, at) for at, tick, _ in commits)
    assert i >= 0 and f >= 0 and ct[-1] >= hi and pt[-1] >= hi
    during = packets[f + 1 : l + 1]
    lag = [ticks[ix(ct, at)] - tick for at, tick in renders if lo <= at <= hi]
    flights = []
    for flight in b.get("sprites", b["throws"]).values():
        start, land = flight["start"], flight["land"]
        if flight["first"] < lo or flight["last"] >= hi:
            continue
        # At accelerated speeds the two model boundaries may fall in one commit.
        left, right = bisect_left(ticks, start), bisect_left(ticks, land)
        end = bisect_right(rt, flight["last"])
        if end >= len(rt) or right >= len(ct):
            continue
        flights.append(
            dict(
                kind=flight["kind"],
                start=start,
                land=land,
                committedMs=round(ct[right] - ct[left], 1),
                paintedMs=round(rt[end] - flight["first"], 1),
            )
        )
    firstRender, lastRender = ix(rt, lo), ix(rt, hi)
    return dict(
        renderedSeconds=round(
            (renders[lastRender][1] - renders[firstRender][1]) / 10, 2
        ),
        observedSprites="sprites" in b,
        windowSeconds=60,
        serverTicks=ticks[j] - ticks[i],
        uiSeconds=round(packets[l][2] - packets[f][2], 2),
        fromRoundClock=packets[f][3:5],
        toRoundClock=packets[l][3:5],
        hudStart=next((text for at, text in b.get("hud", []) if at >= lo), None),
        hudEnd=next(
            (text for at, text in reversed(b.get("hud", [])) if at <= hi), None
        ),
        messages=len(during),
        wsHz=round(len(during) / 60, 2),
        paintHz=round((ix(rt, hi) - ix(rt, lo)) / 60, 2),
        lagTicksP50=nearest_quantile(lag, 0.5),
        lagTicksP95=nearest_quantile(lag, 0.95),
        transitMsP50=nearest_quantile(
            [at - server_time[tick] for at, tick, *_ in during if tick in server_time],
            0.5,
        ),
        parseMsP95=nearest_quantile([p[5] for p in during], 0.95),
        frameCharsP50=nearest_quantile([p[6] for p in during], 0.5),
        commitMsP50=nearest_quantile([c[2] for c in commits[i + 1 : j + 1]], 0.5),
        commitMsP95=nearest_quantile([c[2] for c in commits[i + 1 : j + 1]], 0.95),
        flights=flights,
    )


def routes(folder):
    from backend import cs2_maps

    poses = json.loads((folder / "browser.json").read_bytes())["poses"]
    space = cs2_maps.get(poses[0][2])
    places = json.loads((space.folder / "gameplay.json").read_bytes())["places"]
    # Consecutive visits to surveyed place origins. Require proximity in 3D, even on ramps.
    prior, result = {}, []
    for at, tick, _, agents in poses:
        for ident, x, y, z, weapon, status in agents:
            point = space.world((x, y, z))
            old = prior.get(ident)
            if not old or tick < old["tick"] or tick - old["tick"] > 4:
                old = prior[ident] = dict(
                    point=point, tick=tick, distance=0, visit=None
                )
            if old["tick"] == tick:
                continue
            old["distance"] += dist(point, old["point"])
            old.update(point=point, tick=tick)
            place = min(places, key=lambda p: dist(point, p["position"]))
            offset = dist(point, place["position"])
            if offset > 160:
                continue
            visit = old["visit"]
            if visit and visit[0] != place["name"]:
                elapsed = tick - visit[1]
                if elapsed > 0:
                    result.append(
                        dict(
                            map=space.name,
                            player=ident,
                            weapon=weapon,
                            origin=visit[0],
                            end=place["name"],
                            fromTick=visit[1],
                            toTick=tick,
                            wallSeconds=round((at - visit[2]) / 1000, 3),
                            gameSeconds=round(elapsed / 10, 1),
                            pathHU=round(old["distance"] - visit[3], 1),
                            originErrorHU=round(visit[4]),
                            endErrorHU=round(offset),
                        )
                    )
            if not visit or visit[0] != place["name"] or offset < visit[4]:
                old["visit"] = (place["name"], tick, at, old["distance"], offset)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--routes", action="store_true")
    args = p.parse_args()
    print(
        json.dumps(
            {
                f.name: (routes(f) if args.routes else summarize(f))
                for f in sorted(args.root.iterdir())
                if (f / "browser.json").is_file()
                and (not args.routes or f.name.startswith("route-"))
            },
            ensure_ascii=False,
            indent=2,
        )
    )
