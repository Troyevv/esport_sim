"""Run Valve's pinned JavaScript model and the Python model on identical dated inputs."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

from backend import vrs


def check(repo, archive):
    head = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    if head != vrs.MODEL:
        raise ValueError(f"Expected Valve commit {vrs.MODEL}")
    history = vrs.history()
    with ZipFile(archive) as source:
        raw = json.loads(source.read("matchdata.json"))
    for event in raw["events"]:
        event["finished"] = event["eventId"] in history["events"]
    script = """
const [model, file, end] = process.argv.slice(1);
const [matches, teams] = require(model).generateRanking(Number(end), file);
const rows = teams.filter(t => t.satisfiesRankingCriteria).map(t =>
    [t.name, Math.round(t.rankValue), t.region.indexOf(1), t.activeRoster.map(p => p.nick)]);
process.stdout.write(JSON.stringify([matches.length, rows]));
"""
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "matchdata.json"
        fixture.write_text(json.dumps(raw), encoding="utf-8")
        count, expected = json.loads(subprocess.check_output([
            "node", "-e", script, str(repo.resolve()/"model"/"ranking.js"), str(fixture), str(history["cutoff"])]))
    rows = vrs.calculate(history["matches"], history["events"], history["cutoff"],
                         {pid:p["country"] for pid,p in history["players"].items()},
                         json.loads((vrs.DATA/"vrs-regions.json").read_bytes()))
    actual = [[history["clubs"][r["team"]]["name"],r["points"],["Europe","Americas","Asia"].index(r["region"]),r["nicks"]] for r in rows]
    if count != len(history["matches"]) or expected != actual:
        raise ValueError("Standings differ from Valve's model")
    print(f"{count} series, {len(rows)} identical ranked rosters")


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("repo",type=Path)
    cli.add_argument("archive",type=Path)
    args=cli.parse_args()
    check(args.repo,args.archive)
