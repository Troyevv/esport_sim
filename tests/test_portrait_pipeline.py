import hashlib
import json
from io import BytesIO
from pathlib import Path
from threading import Event
import time

import pytest
from PIL import Image

from backend.portrait_library import PortraitLibrary
from backend.portrait_processing import Unsuitable, PortraitProcessor
from backend.portrait_sources import commons_candidate, commons_search
from tools.import_scene import starter

SAMPLES = Path(__file__).with_name("portrait_samples")


def metadata(person):
    fields = {
        "Artist": "Studio photographer",
        "LicenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "ImageDescription": f"{person['realName']} ({person['name']}) · CS2 official roster portrait",
    }
    return {
        "title": f"File:{person['name']} headshot.jpg",
        "imageinfo": [
            {
                "mime": "image/jpeg",
                "height": 660,
                "width": 660,
                "sha1": "fixture-" + person["pid"],
                "extmetadata": {k: {"value": v} for k, v in fields.items()},
                "url": "https://upload.wikimedia.org/test.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Test.jpg",
            }
        ],
    }


def test_source_and_metadata_guards():
    p = dict(name="Alias", realName="Demo Athlete", team="Demo Club", pid="demo")
    info = metadata(p)
    assert commons_candidate(info, p)
    assert not commons_candidate(
        info, dict(p, name="Other", realName="Another Athlete")
    )
    for field, bad in (
        ("LicenseUrl", "https://creativecommons.org/licenses/by-nd/4.0/"),
        ("ImageDescription", "Demo Athlete Alias CS2 interview with headset"),
    ):
        info = metadata(p)
        info["imageinfo"][0]["extmetadata"][field]["value"] = bad
        assert not commons_candidate(info, p)
    info = metadata(p)
    info["imageinfo"][0]["url"] = "https://unverified.example/photo.jpg"
    assert not commons_candidate(info, p)


def wait(lib):
    deadline = time.monotonic() + 60
    while lib.status()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lib.status()["state"] == "finished", lib.status()


def test_pipeline_searches_caches_retries_and_normalizes(tmp_path):
    p = starter()
    p["players"] = dict(list(p["players"].items())[:2])
    for i, r in enumerate(p["players"].values()):
        r["realName"] = f"Demo Athlete {i}"
    seen = []

    def search(person):
        item = metadata(person)
        response = json.dumps({"query": {"pages": {"1": item}}}).encode()
        yield from commons_search(
            person, lambda url, hosts, size: response, lambda _: None
        )

    def download(url, hosts, limit):
        seen.append(url)
        return (SAMPLES / f"studio-{len(seen) - 1}.jpg").read_bytes()

    lib = PortraitLibrary(tmp_path / "library.sqlite", search, download)
    lib.start(p, "pilot")
    wait(lib)
    assert lib.status()["counts"] == {"done": 2}
    assert len(seen) == 2
    index = lib.index(p["players"])
    for pid, info in index.items():
        digest = info["image"].split("/")[-1]
        pixels = lib.image(digest)
        assert hashlib.sha256(pixels).hexdigest() == digest
        image = Image.open(BytesIO(pixels))
        assert (
            image.mode == "RGBA"
            and image.size == (480, 560)
            and image.getpixel((0, 0))[3] == 0
        )
        assert image.getchannel("A").crop((0, 390, 480, 560)).getextrema()[1] < 10
        assert info["license"] == "CC BY 4.0"
    lib.close()
    lib = PortraitLibrary(tmp_path / "library.sqlite", search, download)
    lib.start(p, "all")
    wait(lib)
    assert len(seen) == 2 and lib.index(p["players"]) == index
    lib.close()


def test_processor_rejects_empty_frame():
    stream = BytesIO()
    Image.new("RGB", (600, 600), "silver").save(stream, format="JPEG")
    proc = PortraitProcessor()
    try:
        with pytest.raises(Unsuitable, match="одно"):
            proc.render(stream.getvalue())
    finally:
        proc.close()


def test_failed_job_can_try_again_and_misses_are_not_free_agents(tmp_path):
    p = starter()
    flag = Event()

    def search(_):
        if not flag.is_set():
            raise RuntimeError("Временная ошибка тестового адаптера")
        return []

    lib = PortraitLibrary(tmp_path / "library.sqlite", search)
    lib.start(p, "pilot")
    lib.thread.join(timeout=10)
    assert lib.status()["state"] == "blocked"
    flag.set()
    lib.start(p, "retry")
    wait(lib)
    assert lib.status()["counts"] == {"skipped": 3} and not lib.index(p["players"])
    lib.close()
