"""Server-owned world snapshot. Exhibition identities survive renames and side changes."""

from datetime import date
from itertools import combinations
from random import Random
from statistics import mean

from . import skills

VERSION = 1
FIXTURE_ROSTERS = ("roster-001", "roster-002")
SLOT_ROLES = ("rifler", "entry", "lurker", "awper", "support")
TEAM_ACTIONS = {"coach_match", "manage_roster", "manage_staff"}
GRANTS = {"manager": TEAM_ACTIONS, "owner": TEAM_ACTIONS | {"allocate_budget", "manage_organization"}}


def authorize(authority, organization, action):
    if authority["organization"] != organization or action not in GRANTS[authority["mode"]]:
        raise ValueError("Недостаточно полномочий в организации")


def pair_key(first, second):
    return "|".join(sorted((first, second)))


def exhibition(agents, legacy=False):
    from .match_rules import CLUBS

    data = dict(version=VERSION, skillVersion=skills.VERSION, players={}, organizations={},
                teams={}, rosters={}, staff={}, chemistry={},
                authority=dict(mode="manager", organization="org-001"))
    for club, roster_id in enumerate(FIXTURE_ROSTERS):
        suffix = f"{club + 1:03}"
        org, team = "org-" + suffix, "team-" + suffix
        data["organizations"][org] = {"name": CLUBS[club]}
        data["teams"][team] = dict(organization=org, name=CLUBS[club])
        data["staff"]["staff-" + suffix] = dict(name=("Ива", "Клён")[club], team=team, role="coach", preparation=65)
        members = []
        for slot, agent in enumerate(agents[club * 5 : club * 5 + 5]):
            number = club * 5 + slot + 1
            ident = f"player-{number:03}"
            role = SLOT_ROLES[slot]
            # Fixture talent belongs to people and is independent of match RNG.
            rng = Random(30601 + number)
            base = {k: rng.randint(43, 83) for k in skills.KEYS}
            for key in skills.ROLE_WEIGHTS["igl" if slot == 0 else role]:
                base[key] = rng.randint(73, 91)
            if legacy:
                base = dict.fromkeys(skills.KEYS, 65)
                for old, key in (("aim", "aim"), ("reaction", "reaction"), ("comms", "communication"), ("tactics", "calling")):
                    base[key] = skills.points(agent[old])
            data["players"][ident] = dict(
                name=agent["name"], skills=base, potential=None if legacy else rng.randint(65, 95),
                mapKnowledge={"depo": 65}, roleMastery={role: 75}, languages=["ru"],
                form=50, morale=50, fatigue=0,
            )
            members.append(dict(player=ident, role=role, captain=slot == 0, since="2026-11-24", until=None))
        data["rosters"][roster_id] = dict(team=team, members=members)
        for a, b in combinations(members, 2):
            data["chemistry"][pair_key(a["player"], b["player"])] = 60
    return data


def lineup(data, roster):
    return [m for m in data["rosters"][roster]["members"] if m["until"] is None]


def validate(data):
    if (data["version"], data["skillVersion"]) != (VERSION, skills.VERSION):
        raise ValueError("Неизвестная версия модели мира или характеристик")
    players, teams, orgs = data["players"], data["teams"], data["organizations"]
    for collection in (players, teams, orgs, data["staff"], data["rosters"]):
        if any(not isinstance(k, str) or not k or "|" in k for k in collection):
            raise ValueError("Некорректный идентификатор сущности")
    for player in players.values():
        if set(player["skills"]) != set(skills.KEYS):
            raise ValueError("Состав каталога характеристик не совпадает с версией")
        if not set(player["roleMastery"]) <= skills.ROLE_WEIGHTS.keys():
            raise ValueError("Неизвестная освоенная роль")
        for value in (*player["skills"].values(), *player["mapKnowledge"].values(),
                      *player["roleMastery"].values(), player["form"], player["morale"], player["fatigue"]):
            skills.points(value)
        if player["potential"] is not None:
            skills.points(player["potential"])
        if not isinstance(player["languages"], list) or not all(isinstance(x, str) and x for x in player["languages"]):
            raise ValueError("Некорректные языки игрока")
    for team in teams.values():
        if team["organization"] not in orgs:
            raise ValueError("Неизвестная организация команды")
    for staff in data["staff"].values():
        if staff["team"] not in teams:
            raise ValueError("Неизвестная команда сотрудника")
        skills.points(staff["preparation"])
    active = set()
    for roster in data["rosters"].values():
        if roster["team"] not in teams:
            raise ValueError("Неизвестная команда состава")
        for m in roster["members"]:
            date.fromisoformat(m["since"])
            if m["until"] is not None and date.fromisoformat(m["until"]) < date.fromisoformat(m["since"]):
                raise ValueError("Некорректный интервал членства")
            if m["player"] not in players or m["role"] not in skills.ROLE_WEIGHTS or type(m["captain"]) is not bool:
                raise ValueError("Некорректное назначение игрока")
            if m["until"] is None:
                if m["player"] in active:
                    raise ValueError("Повторное активное членство игрока")
                active.add(m["player"])
    for key, value in data["chemistry"].items():
        a, b = key.split("|")
        if a not in players or b not in players or not a < b:
            raise ValueError("Некорректная пара сыгранности")
        skills.points(value)
    authority = data["authority"]
    if authority["mode"] not in GRANTS or authority["organization"] not in orgs:
        raise ValueError("Некорректные полномочия")


def validate_five(data, roster):
    members = lineup(data, roster)
    if len(members) != 5 or sum(m["captain"] for m in members) != 1:
        raise ValueError("Для BO1 нужны пять игроков и один капитан")
    return members


def player_report(data, ident):
    """Only the employed club has exact public skills in the exhibition."""
    organization = data["authority"]["organization"]
    player = data["players"][ident]
    report = dict(id=ident, name=player["name"])
    for key, roster in data["rosters"].items():
        org = data["teams"][roster["team"]]["organization"]
        if org == organization and any(m["player"] == ident for m in lineup(data, key)):
            visible = {k: v for k, v in player["skills"].items() if k not in skills.HIDDEN}
            report.update(skills=visible, ratings={r: skills.role_rating(visible, r) for r in skills.ROLE_WEIGHTS})
            break
    return report


def team_rating(data, roster, map_id):
    members = validate_five(data, roster)
    people = data["players"]
    individual, mastery, maps, steadiness = [], [], [], []
    for m in members:
        p = people[m["player"]]
        role = "igl" if m["captain"] else m["role"]
        individual.append(skills.role_rating(p["skills"], role))
        mastery.append(p["roleMastery"].get(m["role"], 0))
        maps.append(p["mapKnowledge"].get(map_id, 0))
        steadiness.append(p["skills"]["concentration"])
    pairs = [data["chemistry"].get(pair_key(a["player"], b["player"]), 0)
             for a, b in combinations(members, 2)]
    staff = [s["preparation"] for s in data["staff"].values() if s["team"] == data["rosters"][roster]["team"]]
    return round(.65 * mean(individual) + .08 * mean(mastery) + .08 * mean(maps)
                 + .10 * mean(pairs) + .05 * (mean(staff) if staff else 0) + .04 * mean(steadiness))
