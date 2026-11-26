"""Select a historical Source 2 tournament demo and export actual round events and radar."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.request import urlopen, urlretrieve

from demoparser2 import DemoParser

from .cs2_pro_demo import parse

ARCHIVE = "skkwowee/chimera-cs2"
REVISION = "2fb9aa50bad67536c04a5b8f6aa2f4b6f908ad71"


def read(url):
    with urlopen(url, timeout=120) as response:
        return response.read()


def candidates(name):
    origin = f"https://huggingface.co/datasets/{ARCHIVE}/resolve/{REVISION}/"
    records = [
        json.loads(line)
        for line in read(origin + "processed_manifest.jsonl").splitlines()
    ]
    for row in sorted(
        records, key=lambda r: (-int(r.get("stars") or 0), -int(r["match_id"]))
    ):
        if int(row["match_id"]) < 2370000:
            continue
        for file in row["demo_files"]:
            if file.lower().endswith(name.removeprefix("de_") + ".dem"):
                yield row | dict(url=origin + file, repo=ARCHIVE, revision=REVISION)
    # Search the public HLTV metadata sidecar by the actual demo filename.
    repo = "blanchon/opencs2_dataset_demo"
    info = json.loads(read("https://huggingface.co/api/datasets/" + repo))
    origin = f"https://huggingface.co/datasets/{repo}/resolve/{info['sha']}/"
    for f in sorted((v["rfilename"] for v in info.get("siblings", [])), reverse=True):
        if not f.lower().endswith(name.removeprefix("de_") + ".dem"):
            continue
        meta = json.loads(read(origin + f.rsplit("/", 1)[0] + "/meta.json"))
        yield meta | dict(url=origin + f, repo=repo, revision=info["sha"])


def rounds_from_events(parser):
    ends = parser.parse_event("round_end").to_dict("records")
    starts = list(parser.parse_event("round_freeze_end")["tick"])
    plants = parser.parse_event("bomb_planted")
    plant_ticks = list(plants["tick"]) if len(plants) else []
    rows = []
    for e in ends:
        end = int(e["tick"])
        previous = rows[-1]["end_tick"] if rows else -1
        start = max((v for v in starts if previous < v < end), default=None)
        if start is None or e["winner"] not in (
            "T",
            "CT",
            "TERRORIST",
            "Terrorist",
            "Terrorists",
            "CounterTerrorist",
            2,
            3,
        ):
            continue
        ct = e["winner"] in ("CT", "CounterTerrorist", 3)
        rows.append(
            dict(
                round_num=len(rows) + 1,
                freeze_end_tick=int(start),
                end_tick=end,
                winner_side="ct" if ct else "t",
                end_reason=str(e["reason"]),
                bomb_planted=any(start <= t <= end for t in plant_ticks),
            )
        )
    if len(rows) < 13 or max(
        sum(r["winner_side"] == s for r in rows) for s in ("t", "ct")
    ) == len(rows):
        raise ValueError(
            f"Unusable rounds ({len(rows)}). Original round_end sample: {ends[:2]}"
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for candidate in candidates(args.map):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "match.dem"
            urlretrieve(candidate["url"], path)
            with path.open("rb") as stream:
                if stream.read(8) != b"PBDEMS2\0":
                    continue
            demo = DemoParser(str(path))
            header = demo.parse_header()
            if header["map_name"] != args.map:
                continue
            rows = rounds_from_events(demo)
            record = dict(
                map=args.map, source=candidate, header=header, rounds=parse(path, rows)
            )
            (args.out / (args.map + "-utility.json")).write_text(
                json.dumps([record], default=str)
            )
            print(
                args.map,
                candidate.get("event"),
                candidate.get("match_id"),
                len(rows),
                flush=True,
            )
            return
    raise ValueError(
        f"No eligible Source 2 tournament demo for {args.map} in archives searched"
    )


if __name__ == "__main__":
    main()
