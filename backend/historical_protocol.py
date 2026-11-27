"""Read-only projection of content-addressed career match reports."""

from .match_rules import LEGACY_VERSION, PREVIOUS_VERSION


def _frozen_rosters(career, pack, event, report):
    """Only editions and roster revisions which actually governed this fixture."""
    registered = {}
    if event.get("edition"):
        edition = career.get("circuit", {}).get("editions", {}).get(event["edition"], {})
        for tid, version in event.get("rosterVersions", {}).items():
            for lineup in edition.get("registrations", {}).get(tid, []):
                if lineup["version"] == version and tid in event["teams"]:
                    registered[tid] = lineup["players"]
    elif not event.get("pcw") and report.get("rules") in (LEGACY_VERSION, PREVIOUS_VERSION):
        # Pre-registration exhibition calendars pin roster IDs in the career's data edition.
        for tid in event["teams"]:
            rid = career["teams"].get(tid)
            roster = pack["rosters"].get(rid)
            if roster and roster["team"] == tid:
                registered[tid] = roster["players"]
    return registered


def normalize(career, pack, event, report):
    """Keep every recorded metric. A null identity denotes missing or conflicting evidence."""
    teams = event["teams"]
    order = report.get("teams", teams)
    if len(order) != 2 or len(set(order)) != 2 or set(order) != set(teams):
        order = []

    def identity(row, field, index):
        explicit = row.get(field)
        slot = row.get(index)
        indexed = order[slot] if type(slot) is int and 0 <= slot < len(order) else None
        if field in row:
            if explicit not in teams or (indexed is not None and indexed != explicit):
                return None
            return explicit
        return indexed

    result = dict(report)
    by_player = {}
    if "maps" in report:
        result["maps"] = [normalize(career, pack, event, m) for m in report["maps"]]
        for m in result["maps"]:
            for row in m["stats"]:
                if row["teamId"] is not None:
                    by_player.setdefault(row["player"], set()).add(row["teamId"])

    frozen = None
    stats = []
    for row in report["stats"]:
        tid = identity(row, "teamId", "club")
        if "teamId" not in row:
            if frozen is None:
                frozen = _frozen_rosters(career, pack, event, report)
            candidates = ({tid} if tid is not None else set()) | by_player.get(row["player"], set()) | {
                t for t, players in frozen.items() if row["player"] in players
            }
            tid = next(iter(candidates)) if len(candidates) == 1 else None
        stats.append(dict(row, teamId=tid))
    result["stats"] = stats
    result["rounds"] = [
        dict(row, winnerTeamId=identity(row, "winnerTeamId", "winner"))
        for row in report["rounds"]
    ]
    return result
