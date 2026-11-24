"""Collect the project's credited Wikimedia thumbnails into a contributor ZIP.

Run from a checkout on a machine with normal access to Wikimedia. Pillow and
external API keys are not needed. Stops on access errors and respects rate limits.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import ZipFile
from urllib.error import HTTPError

SOURCE = Path(__file__).with_name("scene_sources")


def files():
    media = json.loads((SOURCE / "media.json").read_text(encoding="utf-8"))
    guide = json.loads((SOURCE / "commons-portraits.json").read_text(encoding="utf-8"))
    return sorted({v[0] for items in [*media.values(), guide] for v in items.values()})


def thumbnail(name):
    filename = name.replace(" ", "_")
    digest = hashlib.md5(filename.encode()).hexdigest()
    encoded = quote(filename, safe="")
    ext = ".png" if filename.casefold().endswith(".svg") else ""
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{digest[0]}/{digest[:2]}/{encoded}/250px-{encoded}{ext}"


def collect(output):
    tmp = output.with_suffix(".partial")
    with ZipFile(tmp, "w") as archive:
        for name in files():
            req = Request(
                thumbnail(name),
                headers={
                    "User-Agent": "EsportSim/1.0 (https://github.com/Troyevv/esport_sim; credited esports photographs)"
                },
            )
            for attempt in range(2):
                try:
                    with urlopen(req, timeout=45) as response:
                        image = response.read(1024 * 1024 + 1)
                    break
                except HTTPError as exc:
                    if exc.code != 429 or attempt:
                        raise
                    time.sleep(int(exc.headers.get("Retry-After", "60")))
            if len(image) > 1024 * 1024 or not image.startswith(
                (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
            ):
                raise ValueError("Expected a small JPEG or PNG thumbnail for " + name)
            archive.writestr(name, image)
            time.sleep(2)
    tmp.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("r32-media.zip"))
    collect(parser.parse_args().output)
