"""Manual complete BO series replay with the editor, live coach commands and save/load."""
import argparse
import json

from tests.reference_kernel import match
from backend import native_match_state, series, tactics, veto
from tools.compare_full_match import difference
from tools.compare_native_state import encode


def compare(best, seed):
    game = series.initial(seed, best)
    veto.advance(game, "staff")
    maps = []
    while game["series"]["stage"] != "finished":
        game = series.next_map(game)
        owner = native_match_state.open_game(game)

        def same(label):
            actual = json.loads(owner.snapshot())
            reference = json.loads(encode(game))
            if delta := difference(reference, actual):
                raise AssertionError(f"{game['mapId']}, {game['tick']}, {label}: {delta}")

        coach = next(a for a in game["agents"] if a["teamId"] == game["coachTeamId"])
        board = dict(tactics.propose(coach["team"], "Пистолетная", seed, map_id=game["mapId"]),
                     id="r54-series", revision=1)
        match.assign(game, board)
        native_match_state.assign(owner, board)
        same("tactic")
        owner.advance(160)
        for _ in range(160):
            match.advance(game)
        same("board execution")
        match.command(game, "timeout")
        owner.command("timeout", "")
        while game["phase"] not in ("timeout", "finished"):
            match.advance(game)
        while owner.advance(512) == 512:
            pass
        same("deferred timeout")
        owner = native_match_state.open_game(json.loads(owner.snapshot()))
        if game["phase"] == "timeout":
            for kind, value in (("call", "Выход B"), ("resume", None)):
                match.command(game, kind, value)
                owner.command(kind, value or "")
            while game["phase"] != "finished":
                match.advance(game)
            while owner.advance(512) == 512:
                pass
            same("finished")
        native_game = json.loads(owner.snapshot())
        series.finish_map(game)
        series.finish_map(native_game)
        series.validate(native_game)
        if delta := difference(json.loads(encode(game)), native_game):
            raise AssertionError(f"series result: {delta}")
        maps.append([game["mapId"], game["score"], game["tick"]])
    return dict(bestOf=best, seed=seed, maps=maps, score=game["series"]["score"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--best", type=int, required=True, choices=(1, 3, 5))
    parser.add_argument("--seed", type=int, default=140)
    args = parser.parse_args()
    print(json.dumps(compare(args.best, args.seed), ensure_ascii=False))
