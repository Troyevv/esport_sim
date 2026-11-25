"""Public directory of the edition pinned to the active career."""

from . import club_art


def directory(pack, badges, portraits):
    media = f"/api/database/{pack['id']}/{pack['revision']}/media/"

    def identity(group, key, row):
        visual = dict(flag=row.get("nationality") or row.get("region"))
        if group in ("teams", "organizations"):
            badge = badges.get(group + "/" + key) or row.get("logo")
            if group == "teams" and not badge:
                badge = club_art.archive_badge(pack["id"], row)
            visual["club"] = True
            if badge:
                visual["url"] = media + group + "/" + key
                if isinstance(badge, dict):
                    visual["badgeLicense"] = badge.get("license")
        return dict(id=key, name=row["name"], visual=visual)

    teams = {}
    for key, row in pack["teams"].items():
        team = identity("teams", key, row)
        teams[key] = dict(**team, organization=row["organization"], region=row["region"],
                          teamType=row.get("teamType", "unknown"), tier=row["tier"], members=[])
    # A partial, recent roster supersedes an older full five for directory purposes.
    membership = {}
    for _, row in sorted(pack["rosters"].items(), key=lambda pair: (pair[1]["date"], pair[0])):
        if row["date"] <= pack["asOf"]:
            teams[row["team"]]["members"] = row["players"]
            teams[row["team"]]["rosterDate"] = row["date"]
    for tid, team in teams.items():
        for pid in team["members"]:
            membership.setdefault(pid, []).append(tid)
    players = {}
    heads = portraits.index(pack["players"])
    for pid, row in pack["players"].items():
        p = identity("players", pid, row)
        clubs = membership.get(pid, [])
        tid = clubs[0] if len(clubs) == 1 else None
        p["visual"].update(player=True, head=media + "appearance/" + pid if row.get("appearance")
                           else heads.get(pid, {}).get("image"))
        if tid:
            t = teams[tid]
            p["visual"]["kit"] = dict(id=tid, name=t["name"], design=pack["teams"][tid].get("kit"),
                                      badge=t["visual"].get("url"), badgeLicense=t["visual"].get("badgeLicense"))
        players[pid] = dict(**p, teams=clubs, realName=row["realName"], born=row["born"],
                            role=row["role"], contract=row["contract"], statistics=row["statistics"])
    return dict(
        teams=teams, players=players,
        organizations={k: dict(**identity("organizations", k, r), founded=r["founded"])
                       for k, r in pack["organizations"].items()},
        staff={k: dict(**identity("staff", k, r), team=r["team"], role=r["role"], realName=r["realName"])
               for k, r in pack["staff"].items()},
    )
