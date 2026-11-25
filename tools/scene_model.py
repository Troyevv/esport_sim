"""Deterministic, versioned simulation priors. No biographical fact is generated."""

from datetime import date
import hashlib
from math import log1p, sqrt
from backend import database, skills


def noise(key, field):
    raw = hashlib.sha256(("scene-profile-v2/" + key + "/" + field).encode()).digest()
    return (int.from_bytes(raw[:4], "big") / 0xFFFFFFFF) * 2 - 1


def clamp(value, lo=18, hi=97):
    return round(max(lo, min(hi, value)))


def assign(p, pid, obs, historical, rank, role, as_of):
    """Map sample counts, opponent-adjusted series, loadouts and tactical role to game values."""
    r = p["players"][pid]
    games = obs.get("maps", {})
    n = sum(games.values())
    earlier = int(historical["map_count"]) if historical else 0
    weight = n / (n + 24)
    experience = min(1, log1p(n + earlier * 0.4) / log1p(100))
    birth = r.get("born")
    if birth:
        when, born = date.fromisoformat(as_of), date.fromisoformat(birth)
        age = when.year - born.year - ((when.month, when.day) < (born.month, born.day))
    else:
        age = clamp(21.8 + experience * 2.7 + 3.6 * noise(pid, "age"), 17, 34)
        r["ageEstimate"] = age
        r["fields"]["ageEstimate"] = "age-model"
    style = {
        "AWPer": "awper",
        "IGL": "igl",
        "Spacetaker": "entry",
        "Lurker": "lurker",
        "Flex": "rifler",
        "Fill": "support",
    }
    rounds, awp, utility = obs.get("usage", [0, 0, 0])
    rate = awp / max(1, rounds)
    if role:
        r["role"] = role
    elif rounds >= 80 and rate >= 0.20:
        r["role"] = "awper"
    elif historical and style.get(historical["role_overall"]):
        r["role"] = style[historical["role_overall"]]
    else:
        r["role"] = max(
            ("entry", "rifler", "support", "lurker"),
            key=lambda v: noise(pid, "style-" + v),
        )
    r["fields"]["role"] = (
        "scenario"
        if not (
            role
            or rounds >= 80
            and rate >= 0.20
            or historical
            and style.get(historical["role_overall"])
        )
        else "role-estimate"
    )
    specialty = skills.ROLE_WEIGHTS[r["role"]]
    quality = 59 + (max(0, 1 - (rank - 1) ** 0.43 / 12) * 18 if rank else 1)
    residuals = obs.get("residuals", [])
    match_signal = 12 * sum(residuals) / (len(residuals) + 14)
    team_base = quality + match_signal + 4.2 * experience
    personal = r.get("performance")
    performance_signal = 0
    if personal:
        performance_signal = (
            max(-12, min(12, (personal["rating"] - 1.0) * 28))
            * personal["maps"]
            / (personal["maps"] + 35)
        )
    for group, keys in skills.GROUPS.items():
        factor = noise(pid, group) * 7
        for k in keys.split():
            center = team_base + (
                performance_signal
                if group in ("mechanics", "equipment", "tactics")
                else 0
            )
            bias = 3.8 * specialty.get(k, 0)
            if k == "sniper_rifles" and r["role"] != "awper":
                bias -= 12
            if k in ("reaction", "recovery", "endurance"):
                bias += (24 - age) * 0.45
            if k in ("decisions", "calling", "timing", "game_reading"):
                bias += experience * 4
            if group == "mentality" or k in ("discipline", "leadership"):
                center = 62
            if k in ("decoys", "machine_guns", "shotguns"):
                bias -= 9
            if k == "sniper_rifles":
                bias += min(8, rate * 24) * weight
            if k in ("flashes", "smokes") and rounds:
                bias += (utility / rounds - 0.45) * 11 * weight
            if historical and k in ("entry", "aggression", "trades"):
                signal = float(
                    historical["pokt_overall"]
                    if k == "trades"
                    else historical["oap_overall"]
                )
                bias += max(-6, min(6, (signal - 20) * 0.5)) * earlier / (earlier + 30)
            r["skills"][k] = clamp(center + bias + factor + noise(pid, k) * 9)
    r["roleMastery"] = {
        role: clamp(
            skills.role_rating(r["skills"], role)
            + (8 if role == r["role"] else -9)
            + noise(pid, "mastery-" + role) * 5
        )
        for role in skills.ROLE_WEIGHTS
    }
    r["mapKnowledge"] = {
        m: clamp(
            49
            + 12 * experience
            + min(25, 6 * sqrt(games.get(m, 0)))
            + 9 * noise(pid, "map-" + m)
        )
        for m in database.MAPS
    }
    base = skills.role_rating(r["skills"], r["role"])
    r["potential"] = clamp(
        base + max(1, 27 - age) * 1.1 + 4 + 4 * noise(pid, "ceiling"), base, 99
    )
    if n > 0:
        r["fields"]["skills.execution"] = "role-estimate"
    if personal:
        r["fields"]["skills.aim"] = "performance-estimate"
    r["fields"].update(
        skills="scenario",
        potential="scenario",
        mapKnowledge="scenario",
        roleMastery="scenario",
    )
