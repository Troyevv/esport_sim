"""Local brand library shared by the release builder and historical pack display."""

import base64
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).with_name("data") / "club-art"
ARCHIVES = {"austin-registration", "scene-20261124", "scene-202611"}
ALIASES = {
    "Nemesis": "Team Nemesis",
    "5star": "5star eSports",
    "SINNERS": "SINNERS Esports",
    "FURIA": "FURIA Esports",
    "Vitality": "Team Vitality",
    "Falcons": "Team Falcons",
    "Imperial": "Imperial Esports",
    "Spirit": "Team Spirit",
    "Lynn Vision": "Lynn Vision Gaming",
}


@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=320)
def stock(name):
    key = ALIASES.get(name, name)
    item = catalog().get(key)
    if item is None:
        return None
    original = item["kind"] == "original"
    return {
        "image": "/api/database/club-art/" + item["sha256"] + ".png",
        "author": key if original else "EsportSim",
        "source": item["source"],
        "license": item.get("license", "PD-textlogo" if original else "MIT"),
        "changes": (
            "Оригинальная эмблема · локальная копия знака, нормализованы размер и поля."
            if original
            else "Игровая эмблема · " + item["decision"]
        ),
    }


def embedded(name):
    item = stock(name)
    if item is None:
        raise ValueError("Отсутствует эмблема: " + name)
    filename = item["image"].rsplit("/", 1)[1]
    payload = base64.b64encode((ROOT / filename).read_bytes()).decode("ascii")
    return {**item, "image": "data:image/png;base64," + payload}


def archive_badge(pack_id, record):
    if pack_id not in ARCHIVES:
        return None
    custom = record.get("logo")
    if custom is not None:
        # Preserve manual/custom assets even when their club has a stock badge.
        if not isinstance(custom, dict) or not custom.get("image", "").startswith(
            "https://upload.wikimedia.org/"
        ):
            return None
        stock_titles = {
            "Alliance": "Alliance_esports_logo.png",
            "MOUZ": "MOUZlogo2021.png",
            "NRG": "NRG_Esports_logo.svg",
        }
        expected = stock_titles.get(record["name"])
        if (
            not expected
            or custom.get("source")
            != "https://commons.wikimedia.org/wiki/File:" + expected
        ):
            return None
        if unquote(urlsplit(custom["image"]).path.rsplit("/", 1)[-1]) != expected:
            return None
    return stock(record["name"])


def archive_index(pack):
    if pack["id"] not in ARCHIVES:
        return {}
    return {
        group + "/" + key: badge
        for group in ("teams", "organizations")
        for key, row in pack[group].items()
        if (badge := archive_badge(pack["id"], row))
    }
