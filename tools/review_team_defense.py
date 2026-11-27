"""Attribute review windows from audit_team_defense --traces (observer only)."""
import argparse
from collections import Counter
import csv
import gzip
import json
from math import cos, dist, hypot, sin
from pathlib import Path

from backend import cs2_maps
from backend.match_rules import BLAST_RADIUS


def path_left(arena, pos, goal):
    pos, goal = tuple(pos), tuple(goal)
    route = arena.path(arena.locate(pos), pos, arena.locate(goal), goal, frozenset())
    if route is None:
        return None
    length = 0
    for x, y, z, area in route:
        point = (x, y, z)
        length += dist(pos, point)
        pos = point
    return length


def watches(arena, row, site):
    pos, heading = row[3:6], row[18]
    for lane in range(2):
        for q in arena.ingress(site, lane):
            dx, dy = q[0]-pos[0], q[1]-pos[1]
            if (5 < dist(pos, q) < 65 and dx*cos(heading)+dy*sin(heading) >= .5*hypot(dx, dy)
                    and arena.hit(pos, q, 1, 64, 64) is None):
                return True
    return False


def inspect(data):
    arena = cs2_maps.get(data["map"])
    events = data["events"]
    frames = {int(t): {r[0]: r for r in rows if r[6]} for t, rows in data["samples"].items()}
    counts = Counter()
    calls = [e for e in events if e["kind"] == "defense_call"]
    deaths = {e["target"]: e for e in events if e["kind"] == "kill"}
    savers = {}
    plant = next((e for e in events if e["kind"] == "plant"), None)
    planted_at = None
    if plant:
        for tick in range(plant["tick"], plant["tick"]-6, -1):
            planter = frames.get(tick, {}).get(plant["player"])
            if planter:
                planted_at = planter[3:6]
                break
    device, event_index = None, 0
    for t, frame in frames.items():
        while event_index < len(events) and events[event_index]["tick"] <= t:
            event = events[event_index]
            if event["kind"] == "defuse_start":
                device = event["player"]
            if event["kind"] in ("interrupt", "defuse", "explode", "round_end"):
                device = None
            event_index += 1
        angles = []
        for who, r in frame.items():
            if r[1] != "CT":
                continue
            if r[17] == "Сохраняет оружие":
                first, _, start = savers.get(who, (t, None, r[3:6]))
                savers[who] = first, r[3:6], start
            if r[20][0] or r[20][1]:
                counts["groupTicketSamples"] += 1
            if device and who != device:
                counts["liveCoverOpportunities"] += 1
                if r[17] in ("Прикрывает разминирование", "Зачищает подход к обезвреживающему"):
                    counts["coverOrClear"] += 1
                    if r[17] == "Зачищает подход к обезвреживающему":
                        counts["clearSamples"] += 1
                if device in frame and dist(r[3:6], frame[device][3:6]) < 50:
                    angles.append(r[18])
                if r[12] or t-r[14] <= 4:
                    counts["contactDuringUse"] += 1
        if len(angles) >= 2:
            counts["twoNearbySupport"] += 1
            if any(cos(a-b) < .7 for i, a in enumerate(angles) for b in angles[i+1:]):
                counts["twoDifferentHeadings"] += 1
    for who, (t, last, start) in savers.items():
        if planted_at:
            counts["saveBeyondBlastLastSample"] += dist(last, planted_at) >= BLAST_RADIUS
            counts["saveInsideAtStart"] += dist(start, planted_at) < BLAST_RADIUS
        kill = deaths.get(who)
        if kill:
            counts["saveDeathBlast" if kill["weapon"] == "C4" else "saveDeathCombat"] += 1
            counts["ticksFromSaveToDeath"] += kill["tick"]-t
        else:
            counts["survivedSave"] += 1

    for e in events:
        if e["kind"] != "defuse_start":
            continue
        previous = next((c for c in reversed(calls) if c["tick"] <= e["tick"] and "slack" in c), None)
        if previous and previous["decision"] == "retake" and previous["defuser"] == e["player"]:
            delta = e["tick"] - previous["tick"] - previous["eta"][e["player"]]
            counts["assignedUseStarts"] += 1
            counts["assignedUseLater"] += delta > 0
            counts["assignedUseAbsoluteErrorTicks"] += round(abs(delta))

    for idx, e in enumerate(calls):
        if e["decision"] not in ("yield", "regroup"):
            continue
        name = e["decision"]
        t = e["tick"] + (-e["tick"] % 5)
        # Only attribute movement while the measured command was current.
        until = calls[idx+1]["tick"] if idx+1 < len(calls) else t+31
        window = [k for k in range(t, min(t+31, until), 5) if k in frames]
        flags = set()
        for who, goal in e.get("goals", {}).items():
            rows = [(k, frames[k][who]) for k in window if who in frames[k]]
            if not rows:
                continue
            lengths = [path_left(arena, r[3:6], goal) for k, r in rows]
            if any(d is None for d in lengths):
                flags.add("unroutable")
            if lengths[0] is not None:
                if lengths[0] <= 8:
                    flags.add("alreadySet")
                if lengths[0] > 8 and any(d is not None and d <= 8 for d in lengths):
                    flags.add("arrivedFromOutside")
                if any(d is not None and lengths[0]-d > 4 for d in lengths):
                    flags.add("navProgress")
            if any(r[12] or k-r[13] <= 5 or k-r[14] <= 5 for k, r in rows):
                flags.add("contact")
            if any(r[19] >= 5 for _, r in rows):
                flags.add("blocked")
            if any(r[20][0] or r[20][1] for _, r in rows):
                flags.add("groupDuty")
        if until <= t+30:
            flags.add("superseded")
            flags.add("plantTransition" if "slack" in calls[idx+1] else "liveRevision")
        if not window or t+30 not in frames:
            flags.add("shortWindow")
        for flag in flags:
            counts[name+"_"+flag] += 1
        counts[name+"_orders"] += 1

    for e in events:
        if e.get("choice") != "feint":
            continue
        site = e["site"]
        t = e["tick"] + (-e["tick"] % 5)
        begin, end = frames.get(t, {}), frames.get(t+30, {})
        fake = any(r[1] == "T" and r[17] == "Давит на ложный вход" and who in frames.get(k-5, {})
                   and dist(r[3:6], frames[k-5][who][3:6]) > 1
                   for k in range(t+5, t+31, 5) for who, r in frames.get(k, {}).items())
        if not fake:
            continue
        center = arena.site_points[site]
        anchors = [i for i in begin.keys() & end.keys() if begin[i][1] == "CT" and dist(begin[i][3:6], center) <= 55]
        if not anchors:
            continue
        counts["fakeEligible"] += 1
        if any(dist(end[i][3:6], center) <= 55 for i in anchors):
            counts["radiusHeld"] += 1
            continue
        ct = [r for r in end.values() if r[1] == "CT"]
        if any(watches(arena, r, site) for r in ct):
            counts["outsideWithWatchedEntry"] += 1
            if any(watches(arena, end[i], site) for i in anchors):
                counts["sameAnchorWatching"] += 1
        elif any(arena.site_at(r[3:6]) == site or arena.entry_sites.get(arena.locate(tuple(r[3:6]))) == site for r in ct):
            counts["outsideOnSiteNav"] += 1
        elif any(c["site"] != site and c.get("goals", {}).keys() & set(anchors)
                 for c in calls if t-4 <= c["tick"] <= t+30):
            counts["outsideWithNewAwayOrder"] += 1
        else:
            counts["outsideUnresolved"] += 1
    return counts


def main(folder, output):
    matches = {}
    for path in sorted(folder.glob("*.json.gz")):
        policy, seed, start, rnd = path.name.split(".")[0].split("-")
        with gzip.open(path, "rt", encoding="utf-8") as file:
            data = json.load(file)
        key = (policy, data["map"], seed, start)
        matches.setdefault(key, Counter()).update(inspect(data))
    fields = sorted({name for counts in matches.values() for name in counts})
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["policy", "map", "seed", "start", *fields])
        for key, counts in sorted(matches.items()):
            writer.writerow([*key, *(counts[k] for k in fields)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.folder, args.output)
