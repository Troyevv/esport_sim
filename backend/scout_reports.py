"""Organization-owned evidence. All estimates consume observations and public identity only."""

from datetime import date
from functools import lru_cache
from math import sqrt

from .skills import ROLE_WEIGHTS
from zlib import crc32

LEVELS = (
    "Неизвестный",
    "Первичное знакомство",
    "Частично изученный",
    "Хорошо изученный",
    "Досконально изученный",
)
SOURCES = {
    "match": "Официальная встреча",
    "archive": "Публичная статистика",
    "practice": "Пракк",
    "training": "Тренировка",
}
LANGUAGES = {
    "RU": "Русский",
    "Россия": "Русский",
    "BR": "Португальский",
    "PT": "Португальский",
    "FR": "Французский",
    "Франция": "Французский",
    "DE": "Немецкий",
    "DK": "Датский",
    "Дания": "Датский",
    "SE": "Шведский",
    "FI": "Финский",
    "PL": "Польский",
    "US": "Английский",
    "GB": "Английский",
    "CA": "Английский",
    "Великобритания": "Английский",
    "UA": "Украинский",
    "MN": "Монгольский",
    "TR": "Турецкий",
    "ES": "Испанский",
    "CN": "Китайский",
    "EE": "Эстонский",
    "Эстония": "Эстонский",
}


@lru_cache(maxsize=8192)
def ordinal(day):
    return date.fromisoformat(day).toordinal()


def noise(*parts):
    return crc32("/".join(map(str, parts)).encode()) / 4294967295 * 2 - 1


def points(value):
    return min(100, max(0, round(value)))


def band(center, width):
    center = points(center)
    return [points(center - width), points(center + width)]


def mid(interval):
    return sum(interval) / 2


def published_level(rating):
    return points(65 + 35 * (rating - 1))


def performance_signals(s, rounds, role, side):
    # Rates are shrunk towards the observed team average on short maps. Players in
    # entry roles face extra opening duels; an assist is stronger evidence for support.
    reference = side["reference"]
    damage = (s["damage"] - side["damage"]) / (rounds + 12)
    kills = (s["k"] - side["kills"]) / (rounds + 12)
    assists = (s["a"] - side["assists"]) / (rounds + 12)
    attempts = s.get("opening", 0) + s.get("openingDeaths", 0)
    duels = (s.get("opening", 0) - s.get("openingDeaths", 0)) / (attempts + 6)
    exposure = (attempts - side["opening"]) / (rounds + 12)
    survival = (rounds - s["d"] + 2) / (rounds + 4)
    contribution = reference + 0.24 * damage + 30 * kills
    signals = dict(
        aim=points(contribution),
        positioning=points(reference + 32 * (survival - 0.35)),
        support=points(reference + 60 * assists),
    )
    if attempts:
        signals["entry"] = points(reference + 23 * duels + 12 * exposure)
    if s["k"] and "hs" in s:
        signals["first_shot"] = points(
            reference + 36 * ((s["hs"] + 2) / (s["k"] + 4) - 0.5)
        )
    if "kast" in s:
        signals["coordination"] = points(
            reference + 38 * ((s["kast"] + 2) / (rounds + 4) - 0.70)
        )
    # The protocol identifies participation and kills, but does not identify a weapon,
    # an IGL's calls or utility accuracy. Those require other sources.
    role_keys = [k for k in ROLE_WEIGHTS.get(role, {}) if k in signals]
    role_level = (
        sum(signals[k] for k in role_keys) / len(role_keys)
        if role_keys
        else contribution
    )
    level = 0.55 * contribution + 0.45 * role_level
    return signals, points(level)


def observation(fact, person, familiarity, language):
    a = person["attributes"]
    quality = points(
        0.55 * a["ability"]
        + 0.2 * a["discovery"]
        + 0.15 * familiarity
        + 0.1 * (85 if language else 35)
    )
    weight = (0.4 + quality / 100) * min(1.5, max(0.4, fact["sample"] / 22))
    if fact["source"] == "archive":
        weight *= 0.65
    exposure_weight = weight
    if fact.get("maps"):
        # A published multi-map rating has more exposure, but remains one source.
        weight *= min(8, sqrt(fact["maps"]))
    values = {}
    for key, value in fact["signals"].items():
        bias = noise(person["id"], key) * (100 - quality) / 5
        error = noise(person["id"], fact["id"], key) * (100 - quality) / 6
        values[key] = points(value + bias + error)
    measured = (
        fact["level"]
        if "level" in fact
        else sum(fact["signals"].values()) / len(fact["signals"])
    )
    # Basic observers overweight the box score. Reading the level of opposition,
    # the assignment and the player's share of team output requires ability.
    interpretation = quality / 100
    measured = interpretation * measured + (1 - interpretation) * fact.get(
        "rawLevel", measured
    )
    observer_bias = noise(person["id"], "level") * (100 - quality) / 14
    event_error = noise(person["id"], fact["id"], "level") * (100 - quality) / 10
    return dict(
        source=fact["source"],
        event=fact["id"],
        date=fact["date"],
        basis=fact["basis"],
        author=person["id"],
        name=person["name"],
        quality=quality,
        weight=round(weight, 2),
        exposure=round(exposure_weight, 2),
        values=values,
        level=points(measured + observer_bias + event_error),
        context=fact.get("context", False),
        projection=a["potential"],
        fit=a["fit"],
    )


def assessment(observations, today, born=None, role=None, model=2):
    if not observations:
        return dict(
            score=0,
            confidence=0,
            level=LEVELS[0],
            count=0,
            skills={},
            current=None,
            potential=None,
        )
    sums, weights = {}, {}
    total = exposure = 0
    reviews = {}
    measurements = []
    source_totals = {}
    for obs in observations:
        age = max(0, ordinal(today) - ordinal(obs["date"]))
        reviews[obs["event"]] = reviews.get(obs["event"], 0) + 1
        weight = (
            obs["weight"]
            / (1 + age / (180 if model >= 2 else 80))
            / reviews[obs["event"]]
        )
        if obs.get("level") is not None:
            source = obs["source"]
            points_sum, mass = source_totals.get(source, (0, 0))
            source_totals[source] = (points_sum + weight * obs["level"], mass + weight)
            measurements.append(
                (obs["level"], weight, obs["quality"], obs.get("context", False))
            )
        total += weight
        exposure += weight * obs.get("exposure", obs["weight"]) / obs["weight"]
        for key, value in obs["values"].items():
            sums[key] = sums.get(key, 0) + weight * value
            weights[key] = weights.get(key, 0) + weight
    latest = max(o["date"] for o in observations)
    stale = max(0, ordinal(today) - ordinal(latest))
    score = min(
        18 + 14 * len(reviews),
        max(1, points((110 * total / (total + 3)) / (1 + stale / 300))),
    )
    if model >= 2:
        score = min(
            22 + 13 * len(reviews),
            max(1, points(110 * exposure / (exposure + 2.7) / (1 + stale / 660))),
        )
    level = sum(score >= boundary for boundary in (1, 38, 63, 88))
    bands = {
        k: band(sums[k] / w, min(44, 3 + 25 / sqrt(w + 0.3) + stale / 25))
        for k, w in weights.items()
    }
    # A sparse first impression cannot support a full attribute panel.
    keys = sorted(bands, key=lambda k: (-weights[k], k))[
        : (0, 2, 5, 12, len(bands))[level]
    ]
    bands = {k: bands[k] for k in keys}
    center = sum(sums.values()) / sum(weights.values()) if weights else 50
    relevant = {k: w for k, w in ROLE_WEIGHTS.get(role, {}).items() if k in weights}
    if relevant:
        role_level = sum(w * sums[k] / weights[k] for k, w in relevant.items()) / sum(
            relevant.values()
        )
        center = (center + 2 * role_level) / 3
    width = min(44, 4 + 22 / sqrt(total + 0.2) + stale / 25)
    if model >= 2:
        quality = (
            sum(o["weight"] * o["quality"] for o in observations)
            / sum(o["weight"] for o in observations)
            / 100
        )
        # Drift in an unobserved player's trajectory grows with elapsed time. A broad
        # source and poor role coverage retain uncertainty even after many similar games.
        drift = min(29, 0.95 * sqrt(stale))
        coverage = sum(relevant.values()) / max(
            1, sum(ROLE_WEIGHTS.get(role, {}).values())
        )
        floor = 5 + 4 * (1 - quality) + 4 * (1 - coverage)
        # Propagate the unknown components of the actual role formula. The variance
        # of a uniform 0..100 attribute is 100²/12; more box scores do not measure calling.
        profile = ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["rifler"])
        missing_variance = (
            100**2
            / 12
            * sum(
                (w / sum(profile.values())) ** 2
                for k, w in profile.items()
                if k not in weights
            )
        )
        variance = source_variance = 0
        if measurements:
            mass = sum(w for _, w, _, _ in measurements)
            observed = sum(v * w for v, w, _, _ in measurements) / mass
            variance = (
                sum(w * (v - observed) ** 2 for v, w, _, _ in measurements) / mass
            )
            # Disagreement between archive, match and drill measurements is systematic.
            # Repeated matches cannot average away a conflict with another source.
            source_variance = (
                sum(w * (s / w - observed) ** 2 for s, w in source_totals.values())
                / mass
            )
            # Older observations can still contribute when loading pre-calibration saves.
            center = (observed * mass + center * max(0, total - mass)) / total
            if not any(context for _, _, _, context in measurements):
                floor += 2
        width = min(
            44,
            sqrt(
                floor**2
                + missing_variance
                + source_variance
                + ((19 + 10 * (1 - quality)) ** 2 + variance) / (total + 0.35)
                + drift**2
            ),
        )
        bands = {
            k: band(
                sums[k] / weights[k],
                min(
                    44, sqrt((floor + 2) ** 2 + 24**2 / (weights[k] + 0.35) + drift**2)
                ),
            )
            for k in keys
        }
    scout = observations[-1]
    years = (ordinal(today) - ordinal(born)) / 365.25 if born else 25
    future = center + max(4, 25 - max(0, years - 16) * 1.2)
    # A development trend needs comparable measurements on different dates.
    recent, previous = {}, {}
    for obs in sorted(observations, key=lambda o: o["date"]):
        for key, value in obs["values"].items():
            metric = (obs["source"], key) if model >= 2 else key
            previous.setdefault(metric, (obs["date"], value))
            recent[metric] = (obs["date"], value)
    trends = [
        recent[k][1] - v
        for k, (d, v) in previous.items()
        if ordinal(recent[k][0]) - ordinal(d) >= 28
    ]
    if trends:
        future += max(-6, min(6, sum(trends) / len(trends) * 0.3))
    future += noise(scout["author"], "potential") * (100 - scout["projection"]) / 5
    return dict(
        score=score,
        confidence=points(100 * total / (total + 2) / (1 + stale / 240)),
        level=LEVELS[level],
        count=len(observations),
        skills=bands,
        current=band(center, width),
        potential=band(future, width + 5 + (100 - scout["projection"]) / 12),
        last=latest,
        age=stale,
    )


def describe(view, person, observations, roles, languages):
    observation = observations[-1]
    ordered = sorted(view["skills"], key=lambda k: mid(view["skills"][k]))
    role = person.get("role")
    language = LANGUAGES.get(person.get("nationality"))
    center = mid(view["current"])
    needed = role and roles.count(role) <= 1
    confident = view["score"] >= 38 and observation["fit"] >= 40
    style = (
        "Чаще ищет первый контакт"
        if mid(view["skills"].get("entry", [0, 0])) >= 60
        else "Чаще играет за первым номером"
    )
    common = [o["values"]["aim"] for o in observations if "aim" in o["values"]]
    character = "Для оценки устойчивости нужны повторные наблюдения"
    if len(common) >= 3:
        character = (
            "Стабильно исполнял стрелковые задачи"
            if max(common) - min(common) < 18
            else "Исполнение стрелковых задач менялось от игры к игре"
        )
    relevant = ROLE_WEIGHTS.get(role, {})
    observed = {key for obs in observations for key in obs["values"]}
    return dict(
        roleEvidence=(
            f"Наблюдались признаки {len(relevant.keys() & observed)} из {len(relevant)} профильных навыков"
            if relevant
            else "Роль пока не определена"
        ),
        strength=ordered[-1] if ordered else None,
        weakness=ordered[0] if len(ordered) > 1 else None,
        role=role,
        style=style if "entry" in ordered else "Стиль пока не определён",
        character=character,
        language=language,
        fit=(
            (
                "В составе есть место для этой роли"
                if needed
                else "Роль уже представлена в составе"
            )
            if confident and role
            else "Совместимость требует наблюдений"
        ),
        communication=(
            "Общий игровой язык"
            if language and language in languages
            else "Связь предстоит проверить"
        ),
        recommendation=(
            (
                "Пригласить на просмотр"
                if needed and center >= 55
                else "Оставить в шорт-листе"
            )
            if confident
            else "Продолжить наблюдение"
        ),
    )
