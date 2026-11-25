"""Reconfirm independently sourced five-player lineups against the pinned November list."""

import argparse
import gzip
import json
from pathlib import Path
import re
from zipfile import ZipFile
from tools.november_scene import DIR, team_key
from backend.valve_import import COMMIT


def confirm(archive):
    sample = json.loads(gzip.decompress((DIR / "round-sample.json.gz").read_bytes()))
    aliases = sample["players"]
    latest = {}
    for m in sample["maps"]:
        for i, group in enumerate(m["sides"]):
            if group:
                latest[team_key(m["teams"][i])] = list(group)
    found = {}
    with ZipFile(archive) as z:
        for file in sorted(z.namelist()):
            if not file.startswith(
                "invitation/2026/details/2026_11_02/"
            ) or not file.endswith(".md"):
                continue
            body = z.read(file).decode()
            label = re.search(r"^Team Name: (.*?)<br", body, re.M)[1]
            names = {
                n.strip().casefold()
                for n in re.search(r"^Roster: (.*?)<br", body, re.M)[1].split(",")
            }
            key = team_key(label)
            roster = latest.get(key)
            if not roster:
                continue
            matches = [names & {n.casefold() for n in aliases[sid]} for sid in roster]
            if not all(len(m) == 1 for m in matches) or len(set.union(*matches)) != 5:
                continue
            region = re.search(r"^Region: \[(.*?)\]", body, re.M)[1]
            found[key] = {
                "reference": f"https://github.com/ValveSoftware/counter-strike_regional_standings/blob/{COMMIT}/{file}",
                "region": region,
            }
    return found


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    result = confirm(cli.parse_args().archive)
    (DIR / "continuity.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    print(len(result))
