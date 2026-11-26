"""Cold sections of the active checkpoint. Manual slots remain independently readable."""

import hashlib

from pydantic_core import from_json, to_json


class ActiveBulk:
    # The active row and this single companion row are always replaced in one transaction.
    # Values shared with detached workers are immutable strings, never mutable dossier objects.
    def __init__(self, db):
        self.db = db
        db.execute(
            "CREATE TABLE IF NOT EXISTS active_bulk (id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT NOT NULL, body BLOB NOT NULL)"
        )
        self.digest = None
        self.sections = None

    def expand(self, state):
        key = state.pop("bulkDigest", None)
        if key is None:
            return state
        if self.digest != key:
            row = self.db.execute(
                "SELECT body FROM active_bulk WHERE id=1 AND digest=?", (key,)
            ).fetchone()
            if not row or hashlib.sha256(row[0]).hexdigest() != key:
                raise ValueError("Повреждён архив активной карьеры")
            self.sections = from_json(row[0])
            self.digest = key
        training, public, clubs = self.sections
        c = state["career"]
        if training:
            c["training"]["baseline"] = training
        if public:
            c["scouting"]["baseline"] = public
        c["scouting"]["clubs"].update(clubs)
        return state

    def compact(self, state):
        c = state.get("career")
        if not c or "scouting" not in c or "training" not in c:
            return state
        training, scouting = c["training"].copy(), c["scouting"].copy()
        ai = {k: v for k, v in scouting["clubs"].items() if isinstance(v, str)}
        sections = [training.pop("baseline", ""), scouting.pop("baseline", ""), ai]
        if not any(sections):
            return state
        scouting["clubs"] = {k: v for k, v in scouting["clubs"].items() if k not in ai}
        if sections == self.sections:
            digest = self.digest
        else:
            blob = to_json(sections)
            digest = hashlib.sha256(blob).hexdigest()
        # A rollback may have restored the preceding DB generation while the cache was warm.
        row = self.db.execute("SELECT digest FROM active_bulk WHERE id=1").fetchone()
        if not row or row[0] != digest:
            blob = to_json(sections)
            self.db.execute(
                "INSERT OR REPLACE INTO active_bulk VALUES(1,?,?)", (digest, blob)
            )
        self.digest, self.sections = digest, sections
        return dict(
            state,
            bulkDigest=digest,
            career=dict(c, training=training, scouting=scouting),
        )
