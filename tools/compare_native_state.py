"""Replay a real BO1 and compare native state transitions to the live Python reference."""
import argparse
from collections import Counter
from contextlib import ExitStack
import gzip
import json
from pathlib import Path
from unittest.mock import patch

from backend import cs2_economy, cs2_maps, cs2_openings, cs2_play, match, match_ai, native_match_state


def encode(world):
    return json.dumps(world, ensure_ascii=False, separators=(",", ":"))


def compare(checkpoint, combat=False, opening=False, captains=False):
    world = json.loads(gzip.decompress(checkpoint.read_bytes()))
    space = cs2_maps.get(world["mapId"])
    if combat or opening or captains:
        from backend.native_physics import NativePerceptionMap
        physics = NativePerceptionMap(space.folder)
    counts = Counter()
    radio_types = set()
    ref_finish, ref_deliver = match.finish_round, match_ai.deliver_radio

    def same(owner, operation):
        other = json.loads(owner.snapshot())
        if encode(other) != encode(world):
            keys = [k for k in world.keys() | other.keys() if encode(world.get(k)) != encode(other.get(k))]
            raise ValueError(f"{operation} at tick {world['tick']}: {keys}")
        counts[operation] += 1

    def finish(w, side, reason):
        owner = native_match_state.restore(encode(w))
        owner.finish_round(side, reason)
        ref_finish(w, side, reason)
        same(owner, "round_end")

    def deliver(w, players, arena):
        # Compare the first delivery of each payload kind in each BO1. Later
        # deliveries also influence reference inputs for every round settlement.
        kinds = {k for m in w["messages"] if m["due"] <= w["tick"]
                 for k in m.keys() - {"team", "sender", "due"}}
        owner = native_match_state.restore(encode(w)) if kinds - radio_types else None
        ref_deliver(w, players, arena)
        if owner is not None:
            owner.deliver_radio()
            same(owner, "radio")
            radio_types.update(kinds)

    seen_attacks, seen_effects, seen_objectives = set(), set(), set()
    ref_attacks, ref_effects = match.resolve_attacks, match_ai.apply_effects

    def attacks(w, order, players, ids, arena):
        actions = [dict(actor=a["id"], kind=k, target=t)
                   for a, k, t in order if a["hp"] and k in ("shoot", "throw")]
        types = {(a["kind"], a["target"].get("utility") if a["kind"] == "throw"
                  else ids[a["actor"]]["weapon"]) for a in actions}
        owner = native_match_state.restore(encode(w), physics=physics) if types - seen_attacks else None
        if owner is not None:
            owner.resolve_actions(encode(actions))
        ref_attacks(w, order, players, ids, arena)
        if owner is not None:
            same(owner, "attacks")
            seen_attacks.update(types)

    def effects(w, ids, arena):
        types = {f["kind"] for f in w["effects"] if f["land"] == w["tick"]}
        owner = native_match_state.restore(encode(w), physics=physics) if types - seen_effects else None
        if owner is not None:
            owner.apply_effects()
        ref_effects(w, ids, arena)
        if owner is not None:
            same(owner, "effects")
            seen_effects.update(types)

    ref_observe = match_ai.observe
    seen_contacts = set()
    def observation(w, players, arena):
        # Capture first acquisition, continuity, loss and the five guard report slots.
        old = tuple((p["id"], tuple(p["visible"])) for p in players if p["visible"])
        key = (bool(old), w["phase"], w["tick"] % 5, (w["tick"] // 5) % 5)
        owner = native_match_state.restore(encode(w), physics=physics) if key not in seen_contacts else None
        if owner is not None:
            owner.observe()
        ref_observe(w, players, arena)
        if owner is not None:
            same(owner, "observation")
            seen_contacts.add(key)

    ref_resolve = match.resolve_intents
    def resolve(w, intents, players, ids, arena):
        landmarks = {(a["team"], k, w["phase"]) for a, k, _ in intents if k in ("plant", "defuse")}
        if w["action"] and w["action"]["end"] <= w["tick"]:
            landmarks.add(("complete", w["action"]["kind"]))
        if w["deadline"] <= w["tick"]:
            landmarks.add(("deadline", w["phase"]))
        owner = native_match_state.restore(encode(w), physics=physics) if landmarks - seen_objectives else None
        if owner is not None:
            commands = [dict(actor=a["id"], kind=k, target=t) for a, k, t in intents]
            owner.resolve_intents(encode(commands))
        ref_resolve(w, intents, players, ids, arena)
        if owner is not None:
            same(owner, "objectives")
            seen_objectives.update(landmarks)

    ref_decision, ref_buy = cs2_economy.decision, cs2_economy.buy

    def decide(w, squad, call=None, **options):
        expected = ref_decision(w, squad, call, **options)
        owner = native_match_state.restore(encode(w))
        inputs = {k: v for k, v in options.items() if k != "profile"}
        actual = json.loads(owner.buy_decision(squad[0]["team"], encode(dict(call=call, **inputs))))
        if encode(expected) != encode(actual):
            raise ValueError(f"Buy decision differs at tick {w['tick']}")
        counts["budget"] += 1
        return expected

    def buy(w, squad, strategy, purchase, board):
        owner = native_match_state.restore(encode(w))
        owner.buy_equipment(squad[0]["team"], encode(strategy), encode(board))
        ref_buy(w, squad, strategy, purchase, board)
        same(owner, "buy")

    ref_orders = space.orders
    ref_call, ref_select = cs2_play.opening, cs2_openings.select
    ref_read, ref_probe = cs2_play.defensive_read, cs2_play.default_probe

    def verify_choice(expected, actual, owner, name):
        if encode(expected) != encode(json.loads(actual)):
            raise ValueError(f"{name} at tick {world['tick']}: {expected!r} != {actual}")
        same(owner, name)
        return expected

    def call(arena, w, squad, captain, player, buy, site, style, coach):
        owner = native_match_state.restore(encode(w), physics=physics)
        actual = owner.opening_call(captain["team"], buy, site, style, encode(coach))
        expected = ref_call(arena, w, squad, captain, player, buy, site, style, coach)
        return verify_choice(expected, actual, owner, "opening_call")

    def select(arena, plan, squad, players, captain, predicted, explicit):
        owner = native_match_state.restore(encode(world), physics=physics)
        actual = owner.select_defense(encode(plan), encode(predicted), encode(explicit))
        expected = ref_select(arena, plan, squad, players, captain, predicted, explicit)
        return verify_choice(expected, actual, owner, "defense_choice")

    def orders(side, site, squad, lane, style=None):
        owner = native_match_state.restore(encode(world), physics=physics)
        actual = owner.attack_orders(site, lane, style or "") if side == "T" else owner.defense_orders(site, lane)
        expected = ref_orders(side, site, squad, lane, style)
        return verify_choice(expected, actual, owner, "orders_" + side)

    def read(w, captain):
        owner = native_match_state.restore(encode(w))
        return verify_choice(ref_read(w, captain), owner.defensive_read(), owner, "defensive_read")

    def probe(arena, squad, carrier, plan, now, domain):
        owner = native_match_state.restore(encode(world), physics=physics)
        expected = ref_probe(arena, squad, carrier, plan, now, domain)
        return verify_choice(expected, owner.default_probe(encode(plan)), owner, "default_probe")

    seen_reviews = set()
    ref_captain = match_ai.captain

    def review(w, squad, arena):
        leader = min(squad, key=lambda a: (not a["appointed"], a["slot"]))
        side = leader["team"]
        plan = w["plans"][side]
        key = (side, w["phase"], len(squad), leader["id"], leader["heardSite"],
               bool(leader["knowledge"]), bool(leader.get("routeReports")),
               any(r.get("carryingC4") for r in leader["knowledge"].values()),
               bool(plan.get("backup")), bool(plan.get("secondBackup")), bool(plan.get("commitments")),
               plan.get("reinforce"), bool(plan.get("rotated")), w["tick"] >= plan["review"])
        owner = None
        if key not in seen_reviews:
            seen_reviews.add(key)
            owner = native_match_state.restore(encode(w), physics=physics)
            owner.review_captain(side)
        ref_captain(w, squad, arena)
        if owner is not None:
            same(owner, "captain_" + side)

    with ExitStack() as patches:
        patches.enter_context(patch.object(cs2_economy, "decision", decide))
        patches.enter_context(patch.object(cs2_economy, "buy", buy))
        if captains:
            patches.enter_context(patch.object(match_ai, "captain", review))
        if opening:
            patches.enter_context(patch.object(space, "orders", orders))
            patches.enter_context(patch.object(cs2_play, "opening", call))
            patches.enter_context(patch.object(cs2_openings, "select", select))
            patches.enter_context(patch.object(cs2_play, "defensive_read", read))
            patches.enter_context(patch.object(cs2_play, "default_probe", probe))
        if combat:
            patches.enter_context(patch.object(match_ai, "observe", observation))
            patches.enter_context(patch.object(match, "resolve_intents", resolve))
            patches.enter_context(patch.object(match, "resolve_attacks", attacks))
            patches.enter_context(patch.object(match_ai, "apply_effects", effects))
        patches.enter_context(patch.object(match, "finish_round", finish))
        patches.enter_context(patch.object(match_ai, "deliver_radio", deliver))
        while world["phase"] != "finished":
            if world["phase"] == "result":
                owner = native_match_state.restore(encode(world), space)
                ticks = world["deadline"] - world["tick"]
                assert owner.advance_intermission(ticks) == ticks
                for _ in range(ticks):
                    match.advance(world)
                same(owner, "new_round")
            elif opening and world["phase"] == "freeze":
                owner = native_match_state.restore(encode(world), physics=physics)
                ticks = world["deadline"] - world["tick"]
                assert owner.advance_intermission(ticks) == ticks
                for _ in range(ticks):
                    match.advance(world)
                same(owner, "begin_live")
            else:
                match.advance(world)
    return {"map": world["mapId"], "seed": world["seed"], "score": world["score"],
            "ticks": world["tick"], "operations": counts, "radioPayloads": sorted(radio_types)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--combat", action="store_true", help="Also compare first observed attack/utility kinds")
    parser.add_argument("--opening", action="store_true", help="Compare team calls and route choices after freeze time")
    parser.add_argument("--captains", action="store_true", help="Compare active calls as reports and squad size change")
    args = parser.parse_args()
    print(json.dumps(compare(args.checkpoint, args.combat, args.opening, args.captains), ensure_ascii=False))
