"""Profile-wide library. Match checkpoints keep independent frozen copies."""

import json
from uuid import UUID

from . import cs2_maps, engine, tactics
from .match_rules import MAP, ROLES


class StalePlan(ValueError):
    pass


def catalog(db):
    users = [
        dict(json.loads(body), familiarity=mastery)
        for body, mastery in db.execute("""
        SELECT t.body, m.familiarity FROM tactic t
        JOIN (SELECT id, MAX(revision) revision FROM tactic GROUP BY id) latest USING(id, revision)
        JOIN tactic_mastery m USING(id, revision)
        WHERE t.body IS NOT NULL ORDER BY t.rowid DESC
    """)
    ]
    return dict(
        maps=[MAP,*[cs2_maps.description(m) for m in cs2_maps.installed()]],
        roles=ROLES,
        players=engine._NAMES["T"],
        buys=tactics.BUYS,
        plans=users + tactics.standards(),
    )


def resolve(db, value):
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise ValueError("Выберите сохранённую тактику")
    ident = value["id"]
    if ident.startswith("std-"):
        plan = next((p for p in tactics.standards() if p["id"] == ident), None)
    else:
        row = db.execute(
            "SELECT body FROM tactic WHERE id=? ORDER BY revision DESC LIMIT 1",
            (ident,),
        ).fetchone()
        plan = json.loads(row[0]) if row and row[0] else None
    if not plan or plan["revision"] != value.get("revision"):
        raise StalePlan(
            "Версия плана изменилась. Откройте актуальный вариант в библиотеке."
        )
    return plan


def change(db, kind, value):
    if not isinstance(value, dict):
        raise ValueError("Не указан план")
    ident, revision = value.get("id"), value.get("revision")
    if not isinstance(ident, str) or ident.startswith("std-"):
        raise ValueError("Для изменения стандартного плана создайте копию")
    try:
        UUID(ident)
    except ValueError as err:
        raise ValueError("Некорректный идентификатор тактики") from err
    row = db.execute(
        "SELECT revision,body FROM tactic WHERE id=? ORDER BY revision DESC LIMIT 1",
        (ident,),
    ).fetchone()
    if (
        type(revision) is not int
        or revision != (row[0] if row else 0)
        or (row and not row[1])
    ):
        raise StalePlan(
            "План изменён или удалён на другом устройстве. Ваш черновик сохранён на экране."
        )
    body = None
    if kind == "tactic-save":
        plan = dict(
            tactics.validate(value), id=ident, revision=revision + 1, standard=False
        )
        body = json.dumps(plan)
        db.execute("INSERT INTO tactic_mastery VALUES(?,?,0)", (ident, revision + 1))
    elif not row:
        raise ValueError("План ещё не сохранён")
    db.execute("INSERT INTO tactic VALUES(?,?,?)", (ident, revision + 1, body))
