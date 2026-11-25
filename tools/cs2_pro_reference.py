"""Retrieve the published CC-BY professional demo tables for offline map QA."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import pyarrow.parquet as pq

REPO = "sneakyzero/cs2-pro-round-economy"
TABLES = ("full_rounds", "full_team_round_economy", "full_maps")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--revision", default="75c4642627cbb92453ed0736a0a9b6564809e8e8")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with urlopen(f"https://huggingface.co/api/datasets/{REPO}/revision/{args.revision}", timeout=60) as response:
        repo = json.load(response)
    files = [x["rfilename"] for x in repo["siblings"]]
    provenance = {"repository": REPO, "revision": repo["sha"], "sha256": {}}
    for table in TABLES:
        path = next(x for x in files if x.endswith("/" + table + ".parquet"))
        with urlopen(f"https://huggingface.co/datasets/{REPO}/resolve/{repo['sha']}/{path}", timeout=120) as response:
            content = response.read()
        target = args.out / Path(path).name
        target.write_bytes(content)
        provenance["sha256"][path] = hashlib.sha256(content).hexdigest()
        dataset = pq.ParquetFile(target)
        print(table, dataset.metadata.num_rows, dataset.schema.names, flush=True)
    (args.out / "source.json").write_text(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
