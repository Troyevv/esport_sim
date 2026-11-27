"""Content stamps for source preparations protected by a launcher lock."""
import hashlib


def fingerprint(files, base, version=""):
    result = hashlib.sha256(version.encode())
    for path in sorted(files):
        if path.is_file():
            result.update(path.relative_to(base).as_posix().encode() + b"\0")
            result.update(hashlib.sha256(path.read_bytes()).digest())
    return result.hexdigest()


def read_stamp(path):
    try:
        return path.read_text(encoding="ascii")
    except FileNotFoundError:
        return ""


def stamp(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(value, encoding="ascii")
    temp.replace(path)
