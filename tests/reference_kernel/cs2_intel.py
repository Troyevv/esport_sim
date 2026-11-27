"""What an observer can report and the captain can infer from dated contacts."""

from math import cos, dist, hypot, pi, sin

from .cs2_maps import xyz


def observe_contact(sight, opponent, prior, nearby, continuous):
    """Only the item in the visible player's hands and other nearby visible models."""
    sight["weapon"] = opponent["weapon"]
    # Silhouette orientation is observable. The exact aim and target are private.
    sight["bodySector"] = round(opponent["heading"] / (pi / 4)) % 8
    sight["groupSize"] = len(nearby)
    if continuous:
        delta = [v - old for v, old in zip(xyz(sight), xyz(prior))]
        speed = hypot(*delta)
        if speed > 0.05:
            sight["direction"] = [round(v / speed, 3) for v in delta]
            direction = prior.get("direction", ())
            aligned = sum(a * b for a, b in zip(direction, sight["direction"])) >= cos(
                pi / 8
            )
            sight["motionRun"] = 1 + (prior.get("motionRun", 1) if aligned else 0)


def learn_motion(observer, sight, prior):
    """Learn how far a lost contact travelled only when it is seen again."""
    memory = observer.setdefault("motionHistory", {})
    if prior and prior["source"] in ("Зрение", "Радио") and prior.get("direction"):
        elapsed = sight["tick"] - prior["tick"]
        if 1 < elapsed <= 24 and prior.get("speed", 0) > 0:
            length = sum(
                (b - a) * v
                for a, b, v in zip(xyz(prior), xyz(sight), prior["direction"])
            )
            bucket = str(elapsed.bit_length() - 1)
            total, count = memory.get(bucket, (0, 0))
            fraction = max(0, min(1, length / (elapsed * prior["speed"])))
            memory[bucket] = [total + fraction, count + 1]
    if "motionRun" in sight and memory:
        # This snapshot accompanies the dated report. Subsequent observations
        # can change personal experience without rewriting the squad's memory.
        sight["motionHistory"] = memory.copy()


def duel_priority(observer, sight, focus, skills):
    """Estimate exposure from the visible weapon, coarse facing and distance."""
    from backend.match_rules import WEAPONS
    delta = [a-b for a,b in zip(xyz(observer),xyz(sight))]
    gap = hypot(*delta)
    apparent = gap
    if "bodySector" in sight:
        heading = sight["bodySector"] * pi / 4
        alignment = (delta[0]*cos(heading) + delta[1]*sin(heading))/max(1,hypot(*delta[:2]))
        weapon = WEAPONS.get(sight.get("weapon"))
        if weapon:
            # Compare the apparent risk of looking away for an acquisition.
            # A turned opponent must also turn before they can return fire.
            facing_risk = (1 + alignment)/2
            potential = weapon.damage / max(1,weapon.interval)
            apparent /= 1 + facing_risk * potential * skills["game_reading"]/1000
    return apparent - (skills["coordination"]/4 if sight["id"] in focus else 0)


def pressure(space, contacts, now):
    """Aggregate unique opponents. Evidence loses value as they have time to move."""
    counts = dict.fromkeys(("A", "B"), 0.0)
    groups = dict.fromkeys(("A","B"),0.0)
    seen = {}
    for report in contacts:
        old = seen.get(report["id"])
        if report["source"] != "Слух" and (old is None or report["tick"] > old["tick"]):
            seen[report["id"]] = report
    for report in seen.values():
        age = now - report["tick"]
        if not 0 <= age < 75:
            continue
        pos = xyz(report)
        site = space.reported_site(pos)
        approach_only = not site
        if approach_only:
            site = space.entry_sites.get(space.locate(pos)) if hasattr(space,"entry_sites") else None
        if not site:
            continue
        weight = (1 - age / 75) * (0.45 if report["source"] == "Граната" else 1)
        if approach_only:
            weight *= 0.7
        if report.get("carryingC4"):
            weight *= 2
        direction = report.get("direction")
        if direction and age <= 20:
            target = space.site_points[site]
            offset = [b - a for a, b in zip(pos, target)]
            length = hypot(*offset)
            if length > 3:
                alignment = sum(d * v for d, v in zip(direction, offset)) / length
                weight *= 1 + 0.25 * alignment
        counts[site] += weight
        # Several observers can report the same group. Its observed size is a
        # lower bound, never an extra group added to already named opponents.
        groups[site] = max(groups[site], report.get("groupSize",0)*(1-age/75)*(0.7 if approach_only else 1))
    return {site:max(counts[site],groups[site]) for site in counts}


def sector_pressure(space, reports, calls, now, counts):
    """Unidentified audio corroborates a lane, never identifies additional enemies."""
    audio = {"A": {}, "B": {}}
    for r in reports:
        if not r.get("sound") or not 0 <= now - r["tick"] < 32:
            continue
        pos = xyz(r)
        site = space.reported_site(pos) or space.entry_sites.get(space.locate(pos))
        if site:
            strength = r["confidence"] * (1 - (now - r["tick"]) / 32)
            weight = (
                0.84 if r.get("repeated") and r["sound"] == "Шаги" else 0.54
            ) * strength
            audio[site][r["sound"]] = max(audio[site].get(r["sound"], 0), weight)
    for site in counts:
        # Even repeated noises in one lane can release at most one reserve.
        counts[site] += min(0.94, sum(audio[site].values()))
        recent = [c for c in calls if c["site"] == site and 0 <= now - c["tick"] < 35]
        # A blocked path or a missing partner calls for new coverage. It is
        # not evidence that an opponent is there. Require independent contact.
        if any(c["state"] in ("unsupported", "engaged") for c in recent) and any(
            r["source"] in ("Радио", "Зрение")
            and now - r["tick"] < 25
            and (
                space.reported_site(xyz(r))
                or space.entry_sites.get(space.locate(xyz(r)))
            )
            == site
            for r in reports
        ):
            counts[site] += 0.68
        # Cleared angles supersede only older observations of that same angle.
        for call in recent:
            if call["state"] != "watching":
                continue
            if any(
                r["source"] in ("Зрение", "Радио")
                and r["tick"] >= call["tick"]
                and dist(xyz(r), tuple(call["point"])) < 30
                for r in reports
            ):
                continue
            if any(
                r["tick"] < call["tick"] and dist(xyz(r), tuple(call["point"])) < 25
                for r in reports
            ):
                counts[site] = max(0, counts[site] - 0.45)
                break


def sniper_lane(space, reports, order, now):
    """Identify a long, exposed crossing covered by a recently reported AWP."""
    for report in reports:
        if report.get("weapon") != "AWP" or now - report["tick"] > 25:
            continue
        pos = xyz(report)
        for point in order["via"][-2:]:
            if 30 < dist(pos, point) < 100 and space.hit(pos, point, 1, 64) is None:
                return True
    return False
