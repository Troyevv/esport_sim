"""Pinned addition to the November career directory for the CCT Europe 16 field."""

import json
from functools import lru_cache

from . import database, valve_import
from .competition_catalog import DATA

EDITION = "cct-eu16-lineups-v1"


@lru_cache(maxsize=1)
def lineups():
    return json.loads((DATA / (EDITION + ".json")).read_bytes())


def source(key, revision):
    return (
        [key, revision, EDITION]
        if key == database.RELEASE_ID and revision == 1
        else [key, revision]
    )


def extend(base):
    pack = dict(base, tournamentSupplement=EDITION)
    for key in ("teams", "players", "rosters", "origins"):
        pack[key] = base[key].copy()
    for team in lineups():
        tid = team["id"]
        origin = EDITION + "-" + tid
        pack["origins"][origin] = valve_import.origin(
            "confirmed", team["observed"], team["source"]
        )
        if tid not in pack["teams"]:
            pack["teams"][tid] = valve_import.row(
                team["name"], origin, organization=None, region="Europe", tier=3
            )
            pack["teams"][tid]["fields"]["tier"] = "model"
        members = []
        for member in team["players"]:
            pid = member["id"]
            members.append(pid)
            if pid not in pack["players"]:
                fresh = {"players": {}}
                default = valve_import.person(fresh, member["name"], origin)
                pack["players"][pid] = dict(
                    fresh["players"][default], nationality=member["country"]
                )
        rid = "zz-cct16-" + tid
        pack["rosters"][rid] = valve_import.row(
            team["name"] + " · CCT Europe 16",
            origin,
            team=tid,
            date=base["asOf"],
            players=members,
            captain=None,
        )
    return pack
