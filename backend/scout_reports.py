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


def match_signals(stats, rounds):
    return dict(
        aim=points(24 + 54 * stats["k"] / rounds),
        positioning=points(99 - 48 * stats["d"] / rounds),
        trades=points(41 + 75 * stats["a"] / rounds),
        entry=points(48 + 95 * stats.get("opening", 0) / rounds),
        rifles=points(24 + 0.48 * stats["damage"] / rounds),
    )


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
    values = {}
    for key, value in fact["signals"].items():
        bias = noise(person["id"], key) * (100 - quality) / 5
        error = noise(person["id"], fact["id"], key) * (100 - quality) / 6
        values[key] = points(value + bias + error)
    return dict(
        source=fact["source"],
        event=fact["id"],
        date=fact["date"],
        basis=fact["basis"],
        author=person["id"],
        name=person["name"],
        quality=quality,
        weight=round(weight, 2),
        values=values,
        projection=a["potential"],
        fit=a["fit"],
    )


def assessment(observations, today, born=None, role=None):
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
    total = 0
    reviews = {}
    for obs in observations:
        age = max(0, ordinal(today) - ordinal(obs["date"]))
        reviews[obs["event"]] = reviews.get(obs["event"], 0) + 1
        weight = obs["weight"] / (1 + age / 80) / reviews[obs["event"]]
        total += weight
        for key, value in obs["values"].items():
            sums[key] = sums.get(key, 0) + weight * value
            weights[key] = weights.get(key, 0) + weight
    latest = max(o["date"] for o in observations)
    stale = max(0, ordinal(today) - ordinal(latest))
    score = min(
        18 + 14 * len(reviews),
        max(1, points((110 * total / (total + 3)) / (1 + stale / 300))),
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
    center = sum(sums.values()) / sum(weights.values())
    relevant = {k: w for k, w in ROLE_WEIGHTS.get(role, {}).items() if k in weights}
    if relevant:
        role_level = sum(w * sums[k] / weights[k] for k, w in relevant.items()) / sum(
            relevant.values()
        )
        center = (center + 2 * role_level) / 3
    width = min(44, 4 + 22 / sqrt(total + 0.2) + stale / 25)
    scout = observations[-1]
    years = (ordinal(today) - ordinal(born)) / 365.25 if born else 25
    future = center + max(4, 25 - max(0, years - 16) * 1.2)
    # A development trend needs comparable measurements on different dates.
    recent, previous = {}, {}
    for obs in sorted(observations, key=lambda o: o["date"]):
        for key, value in obs["values"].items():
            previous.setdefault(key, (obs["date"], value))
            recent[key] = (obs["date"], value)
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
    return dict(
        strength=ordered[-1],
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
