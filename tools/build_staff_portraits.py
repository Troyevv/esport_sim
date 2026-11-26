"""Pack chroma-keyed, generated head sheets into independently cacheable WebP images."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend import competition_scene, database

DATA = database.STARTER.parent


def cutouts(path):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    red, green, blue = rgb.transpose(2, 0, 1)
    excess = green - np.maximum(red, blue)
    mask = ((excess < 44) | (green < 65)).astype(np.uint8)
    _, labels, boxes, _ = cv2.connectedComponentsWithStats(mask)
    height, width = mask.shape
    # Find actual heads rather than cutting a nominal 8x8 grid through hair.
    for label, (x, y, w, h, area) in sorted(
        enumerate(boxes[1:], 1), key=lambda b: (b[1][1], b[1][0])
    ):
        if not (
            width * 0.055 < w < width * 0.16
            and height * 0.072 < h < height * 0.155
            and area > w * h * 0.40
        ):
            continue
        if not 0.48 < w / h < 1.22:
            continue
        pixels = rgb[y : y + h, x : x + w].copy()
        alpha = (labels[y : y + h, x : x + w] == label).astype(np.uint8) * 255
        # Suppress green spill along antialiased hair boundaries.
        pixels[:, :, 1] = np.minimum(
            pixels[:, :, 1], np.maximum(pixels[:, :, 0], pixels[:, :, 2]) + 8
        )
        rgba = Image.fromarray(np.dstack((pixels.astype(np.uint8), alpha)))
        rgba.thumbnail((114, 151), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (240, 280))
        # The generated crop ends at the neck. Extend those same neck pixels
        # under the front collar, leaving the jaw, hair and upper neck intact.
        cx = rgba.width // 2
        radius = min(20, round(rgba.width * 0.19))
        strip = rgba.crop((cx - radius, rgba.height - 7, cx + radius, rgba.height - 2))
        neck = strip.resize((2 * radius, 24), Image.Resampling.BICUBIC)
        canvas.paste(neck, (120 - radius, 151))
        canvas.alpha_composite(rgba, ((240 - rgba.width) // 2, 158 - rgba.height))
        stream = io.BytesIO()
        canvas.save(stream, "WEBP", quality=86, method=5)
        yield stream.getvalue()


def main(folder):
    pack = competition_scene.extend(
        json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    )
    archive = json.loads(database.STARTER.read_bytes())["package"]
    women = {
        pid
        for r in pack["rosters"].values()
        if pack["teams"][r["team"]]["name"] in ("BIG EQUIPA", "Shimmer", "girl kissers")
        for pid in r["players"]
    }
    women.update(
        pid
        for pid, row in pack["players"].items()
        if row["name"].casefold()
        in ("kaahsensei", "gabs", "bizinha", "tory", "vicu", "twenty3")
    )
    women.add("staff-marta-minopolis")
    ages = {}
    aliases = {}
    named = {}
    by_nick = {}
    for edition in (pack, archive):
        for group in ("players", "staff"):
            for pid, row in sorted(edition[group].items()):
                if pid in ages:
                    continue
                key = (row["name"].casefold(), row.get("realName"))
                if edition is archive:
                    matches = (
                        named.get(key, [])
                        if key[1]
                        else by_nick.get((group, key[0]), [])
                    )
                    if len(matches) == 1:
                        aliases[pid] = matches[0]
                        continue
                named.setdefault(key, []).append(pid)
                by_nick.setdefault((group, key[0]), []).append(pid)
                ages[pid] = (
                    int(edition["asOf"][:4]) - int(row["born"][:4])
                    if row.get("born")
                    else row.get("ageEstimate") or (37 if group == "staff" else 23)
                )
    for name, *_ in json.loads((DATA / "staff-20261125.json").read_bytes()):
        ages["staff-" + name.lower().replace(" ", "-").rstrip("-")] = 36
    for sid, bio in json.loads((DATA / "staff-biographies.json").read_bytes()).items():
        if bio.get("born"):
            ages[sid] = 2026 - int(bio["born"][:4]) - (bio["born"][5:] > "11-25")
    faces = []
    seen = set()
    for sheet in sorted(folder.glob("r51-*.png")):
        try:
            index = int(sheet.stem.split("-")[-1])
        except ValueError:
            continue
        age = (
            38
            if index in (28, 29)
            else 19
            if index == 30
            else 30
            if index in (23, 24, 25, 26, 27, 32)
            else 23
        )
        for tile, raw in enumerate(cutouts(sheet)):
            digest = hashlib.sha256(raw).hexdigest()
            if digest not in seen:
                seen.add(digest)
                faces.append((age, index, tile, digest, raw))
    if len(faces) < len(ages):
        raise ValueError(f"Недостаточно разных лиц: {len(faces)} из {len(ages)}")
    atlas = bytearray()
    entries = {}
    people = {}
    # Reserve the oldest and youngest sheets first, then fill the central cohort.
    for pid, a in sorted(ages.items(), key=lambda pair: (-abs(pair[1] - 23), pair[0])):
        at = min(
            range(len(faces)),
            key=lambda i: (
                int((pid in women) != (faces[i][1] == 35)),
                abs(faces[i][0] - a),
            ),
        )
        _, sheet, tile, digest, raw = faces.pop(at)
        entries[digest] = [len(atlas), len(raw), sheet, tile]
        atlas.extend(raw)
        people[pid] = digest
    people.update({pid: people[source] for pid, source in aliases.items()})
    info = dict(
        version=1,
        synthetic=True,
        generator="OpenAI ImageGen",
        source="https://openai.com/policies/terms-of-use/",
        terms="OpenAI Terms of Use, Ownership of content",
        assets=entries,
        people=people,
    )
    (DATA / "heads-v1.bin").write_bytes(atlas)
    (DATA / "heads-v1.json").write_text(database.encode(info), encoding="utf8")
    print(len(people), "identities,", len(entries), "faces,", len(atlas), "bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    main(parser.parse_args().folder)
