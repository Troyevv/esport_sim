"""Run the same deterministic simulation without HTTP, SQLite or rendering."""

import argparse
import hashlib
import json
import platform
import time
import tracemalloc

from . import engine, match


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ticks", type=int, default=1200)
    parser.add_argument(
        "--bo1", action="store_true", help="Сыграть полный выставочный BO1 на Депо"
    )
    parser.add_argument("--map",default="depo",help="Идентификатор установленной карты BO1")
    args = parser.parse_args()
    if args.ticks < 0:
        parser.error("--ticks must be non-negative")
    tracemalloc.start()
    started = time.perf_counter()
    if args.bo1:
        state = match.initial(args.seed,map_id=args.map)
        while state["phase"] != "finished":
            match.advance(state)
    else:
        state = engine.initial(args.seed)
        for _ in range(args.ticks):
            engine.advance(state)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    print(
        json.dumps(
            dict(
                python=platform.python_version(),
                machine=platform.machine(),
                seed=args.seed,
                ticks=state["tick"],
                **(
                    {
                        "map": state.get("mapId","depo"),
                        "rules": state["rules"],
                        "score": state["score"],
                        "events": state["serial"],
                    }
                    if args.bo1
                    else {}
                ),
                simulated_s=state["tick"] * engine.TICK_SECONDS,
                wall_s=round(elapsed, 4),
                peak_python_bytes=peak,
                sha256=hashlib.sha256(encoded).hexdigest(),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
