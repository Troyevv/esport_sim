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
from backend.portrait_sources import commons_candidate, commons_search, previously_rejected
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


def test_excluded_portraits_stay_excluded_across_commons_crop_aliases():
    assert previously_rejected("https://commons.wikimedia.org/wiki/File:Astralis_dev1ce_2020_interview_(cropped).jpg")
    assert previously_rejected("https://upload.wikimedia.org/wikipedia/commons/d/d1/Astralis_dev1ce_2020_interview_%28cropped_2%29.jpg")
    assert not previously_rejected("https://commons.wikimedia.org/wiki/File:Dev1ce_studio_portrait_2026.jpg")


def wait(lib, expected="finished"):
    deadline = time.monotonic() + 60
    while lib.status()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lib.status()["state"] == expected, lib.status()


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
    wait(lib, "blocked")
    flag.set()
    lib.start(p, "retry")
    wait(lib)
    assert lib.status()["counts"] == {"skipped": 3} and not lib.index(p["players"])
    lib.close()


def test_public_flickr_verifies_license_on_each_entry():
    from backend.portrait_sources import public_flickr

    p = dict(name="Alias", realName="Demo Athlete", team="Demo Club")
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <title>Demo Athlete (Alias), CS2 official roster portrait</title>
    <author><name>Studio</name></author>
    <link rel="license" href="https://creativecommons.org/licenses/by/4.0/"/>
    <link rel="alternate" href="https://www.flickr.com/photos/test/1/"/>
    <link rel="enclosure" href="https://live.staticflickr.com/test.jpg"/>
    </entry></feed>"""
    assert len(list(public_flickr(p, lambda *_: xml))) == 1
    assert not list(public_flickr(p, lambda *_: xml.replace(b"by/4.0", b"by-nc/4.0")))
    assert not list(
        public_flickr(p, lambda *_: xml.replace(b'rel="license"', b'rel="related"'))
    )


def test_pause_and_retry_do_not_publish_stale_work(tmp_path):
    started = Event()
    release = Event()

    def search(_):
        started.set()
        release.wait(5)
        return []

    pack = starter()
    lib = PortraitLibrary(tmp_path / "library.sqlite", search)
    lib.start(pack, "pilot")
    assert started.wait(5)
    with pytest.raises(ValueError, match="уже"):
        lib.start(pack, "all")
    assert lib.pause()["state"] == "paused"
    lib.start(pack, "retry")
    release.set()
    wait(lib)
    assert lib.status()["counts"] == {"skipped": 3}
    lib.close()


def test_rate_limit_applies_to_later_players_on_same_host(monkeypatch):
    from email.message import Message
    from urllib.error import HTTPError
    from backend import portrait_sources as sources

    host = "commons.wikimedia.org"
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            headers = Message()
            headers["Retry-After"] = "90"
            raise HTTPError(request.full_url, 429, "Rate limit", headers, None)

    now_ns = 30_920_100_000_001
    monkeypatch.setattr(sources.time, "monotonic_ns", lambda: now_ns)
    monkeypatch.setattr(sources, "_backoff", {})
    monkeypatch.setattr(sources, "build_opener", lambda *_: Opener())
    for path in ("/one", "/two"):
        with pytest.raises(sources.Unavailable, match="429") as exc:
            sources.fetch("https://" + host + path, {host}, 1000)
        assert exc.value.delay == 90
    now_ns += 89_999_999_999
    with pytest.raises(sources.Unavailable) as exc:
        sources.check_host("https://" + host)
    assert exc.value.delay == 1
    now_ns += 1
    sources.check_host("https://" + host)
    assert len(calls) == 1
