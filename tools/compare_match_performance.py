"""Manual serial BO1 comparison. Run after building Release, on an idle host."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from backend.cs2_maps import NAMES


def compare(folder, seeds, cpu):
    if cpu is not None:
        os.sched_setaffinity(0, {cpu})
    env = os.environ | dict(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONHASHSEED="0")
    modes = [("python", []), ("hybrid", ["--native-physics"]), ("cpp", ["--native-core"])]
    for seed in seeds:
        for index, name in enumerate(NAMES):
            expected = None
            for mode, options in modes[index % 3:] + modes[:index % 3]:
                out = folder / str(seed) / mode
                subprocess.run([sys.executable, "-m", "tools.measure_detailed_match",
                                "--map", name, "--seed", str(seed), "--restore",
                                "--out", str(out), *options], env=env, check=True)
                report = json.loads((out / f"{name}.json").read_bytes())
                controls = report["controls"]
                if expected is not None and controls != expected:
                    different = [key for key in controls if controls[key] != expected[key]]
                    raise ValueError(f"{seed} {name} {mode}: {different}")
                expected = controls


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=[41000])
    parser.add_argument("--cpu", type=int, help="Pin the benchmark and children to one CPU on Linux")
    args = parser.parse_args()
    if args.cpu is not None and not hasattr(os, "sched_setaffinity"):
        parser.error("--cpu requires sched_setaffinity")
    compare(args.out, args.seeds, args.cpu)
