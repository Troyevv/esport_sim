"""Content-addressed generated appearances shared by the database, career and match projections."""

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).with_name("data")


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT / "heads-v1.json").read_bytes())


def synthetic(person):
    digest = catalog()["people"].get(person)
    if digest:
        return dict(
            image="/api/portraits/generated/" + digest,
            author="OpenAI ImageGen",
            synthetic=True,
            license="OpenAI Terms of Use",
            source=catalog()["source"],
            changes="Синтетический игровой портрет",
        )


def index(pack, library):
    records = {**pack["players"], **pack["staff"]}
    result = {pid: asset for pid in records if (asset := synthetic(pid))}
    result.update(
        {
            pid: dict(asset, synthetic=False)
            for pid, asset in library.index(records).items()
        }
    )
    return result


def read(digest):
    entry = catalog()["assets"].get(digest)
    if not entry:
        return None
    with (ROOT / "heads-v1.bin").open("rb") as file:
        file.seek(entry[0])
        return file.read(entry[1])
