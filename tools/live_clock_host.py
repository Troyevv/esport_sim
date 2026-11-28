"""Manual wall-clock acceptance host. Uses a real saved BO1 and the production ASGI app."""

import argparse
import json
import time
from pathlib import Path

import uvicorn

from backend import native_match_state
from backend.server import create_app
from backend.store import Store
from tools.review_coaching_matches import fixture


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--map", default="de_mirage")
    parser.add_argument("--coach", action="store_true")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--tick", type=int, default=0)
    parser.add_argument("--speed", type=int, choices=(1, 2, 4, 8), default=1)
    parser.add_argument("--service-ms", type=float, default=0)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    db = args.directory / "match.sqlite"
    if db.exists():
        parser.error("Choose a new output directory for this measurement")
    store = Store(db)
    state = store.read()
    world = fixture(args.map, 56705, 0)
    world["autonomous"] = not args.coach
    if args.tick:
        owner = native_match_state.open_game(world)
        owner.advance(args.tick)
        world = json.loads(owner.snapshot())
        del owner
    state.update(world=world, running=False, speed=args.speed)
    with store.transaction():
        store.write(state)
    store.portraits.close()
    store.badges.close()
    store.db.close()
    original = Store.tick
    with (args.directory / "commit.jsonl").open("w", buffering=1) as commits:

        def instrument(self, *a, **kw):
            start = time.perf_counter()
            advanced = original(self, *a, **kw)
            if advanced:
                committed = time.time()
                elapsed = time.perf_counter() - start
                commits.write(
                    json.dumps([committed, self.motion[-1][2], elapsed]) + "\n"
                )
                if args.service_ms:
                    time.sleep(max(0, args.service_ms / 1000 - elapsed))
            return advanced

        Store.tick = instrument
        uvicorn.run(
            create_app(db, managed=False),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
