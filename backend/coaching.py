"""Match staff inputs and the coach's restricted view of a tactical break."""

from . import scene_portraits, staff


def bench(domain):
    result = {}
    for team in domain["teams"]:
        coaches = [
            (row.get("matchRole", staff.position(row["role"])) == "head", row["preparation"], sid, row)
            for sid, row in domain["staff"].items()
            if row["team"] == team
        ]
        if not coaches:
            result[team] = dict(analysis=40, support=35, bold=False)
            continue
        _, preparation, sid, row = max(coaches)
        profile = staff.profile(sid, row)
        a = profile["attributes"]
        support = (a["mental"] + a["communication"] + a["motivation"]) // 3
        specialists = [
            staff.profile(i, r)["attributes"]["mental"]
            for i, r in domain["staff"].items()
            if r["team"] == team and r.get("matchRole", staff.position(r["role"])) == "psychologist"
        ]
        if specialists:
            support += max(0, max(specialists) - support) // 3
        result[team] = dict(
            analysis=(a["reading"] + a["matches"] + preparation) // 3,
            support=support,
            bold=profile["philosophy"]["Стиль игры"] == "Агрессивный",
        )
    return result


def validate_address(value):
    if (
        not isinstance(value, dict)
        or not {"action", "target", "subject"} <= value.keys()
        or value.keys() - {"action", "target", "subject", "speaker", "order", "mate", "site"}
        or type(value["subject"]) is not int
        or not 0 <= value["subject"] <= 2**53
        or any(not isinstance(v, str) or len(v) > 96 for k, v in value.items() if k != "subject")
    ):
        raise ValueError("Некорректный адресат или предмет обсуждения")


def impression(mind, detail):
    stress, frustration, confidence = (mind[k] for k in ("stress", "frustration", "confidence"))
    if frustration >= 48 and mind["focus"] < -6:
        return "Подвержен тильту" if detail else "Раздражён"
    if stress > 51:
        return "Нервничает" if detail else "Напряжён"
    if frustration > 32:
        return "Раздражён"
    if mind["focus"] < -8:
        return "Теряет концентрацию"
    if confidence < 39:
        return "Не уверен в себе"
    if confidence > 78:
        return "Чрезмерно уверен" if detail else "Уверен"
    if confidence > 65 and mind["initiative"] > 7:
        return "Воодушевлён"
    if confidence > 59:
        return "Уверен"
    if stress > 34:
        return "Напряжён"
    return "Собран" if mind["focus"] >= 2 else "Спокоен"


def room(w, permitted, roster):
    if not permitted or "talkSeconds" not in w or w["phase"] != "timeout":
        return None
    team = w["coachTeamId"]
    detail = w["coaches"][team]["support"] >= 55
    players = {}
    fixture = w["domain"]["source"]["id"] == "depo-exhibition"
    heads = list(scene_portraits.catalog()["assets"])[:10] if fixture else []
    for a in roster:
        p = w["domain"]["players"][a["playerId"]]
        morale = p["morale"] + (a["mind"]["confidence"] - 50) // 4 - a["mind"]["frustration"] // 4
        players[a["id"]] = dict(
            state=impression(a["mind"], detail),
            morale="На подъёме" if morale > 62 else "Подавлен" if morale < 39 else "Ровная",
            fatigue="Устал" if p["fatigue"] > 55 else "Утомлён" if p["fatigue"] > 27 else "Свеж",
            topics=a["topics"],
            order=a.get("coachOrder"),
            head="/api/portraits/generated/" + heads[a["club"] * 5 + a["slot"]] if heads else None,
        )
    return dict(
        seconds=w["talkSeconds"],
        players=players,
        history=[row for row in w["talkHistory"] if row["team"] == team and row["round"] == w["round"]],
    )
