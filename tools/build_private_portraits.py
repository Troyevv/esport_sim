"""Rebuild the reviewed local-only pack from exact versions of its studio sources."""

import argparse
import hashlib
import os
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from PIL import Image

from backend.personal_portraits import catalog
from backend.portrait_processing import PortraitProcessor


def build(roots, output):
    processor = PortraitProcessor()
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temp:
            tmp = Path(temp.name)
        try:
            with ZipFile(tmp, "w", compression=ZIP_STORED) as archive:
                for entry in catalog().values():
                    _, owner, repo, _, _, rel = urlsplit(entry["source"]).path.split(
                        "/", 5
                    )
                    raw = (roots / owner / repo / unquote(rel)).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != entry["originalSha256"]:
                        raise ValueError("Изменился исходник " + entry["name"])
                    if entry.get("frame"):
                        with Image.open(BytesIO(raw)) as im:
                            crop = im.convert("RGBA").crop(entry["frame"])
                        stream = BytesIO()
                        crop.save(stream, "PNG")
                        rendered = processor.render(stream.getvalue())
                    else:
                        rendered, _ = processor.render_roster(raw)
                    sha = hashlib.sha256(rendered).hexdigest()
                    if sha != entry["sha256"]:
                        raise ValueError(
                            "Слой требует повторной проверки: " + entry["name"]
                        )
                    archive.writestr(
                        ZipInfo(sha + ".png", (2026, 11, 25, 0, 0, 0)), rendered
                    )
            os.replace(tmp, output)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        processor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots", type=Path, help="Directory of owner/repository checkouts"
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.roots, args.output)
