"""Manual R5.6 full-match acceptance. One mirrored leg per process, no CI work."""

import argparse
import gzip
import json
from collections import Counter, defaultdict
from math import atan2, cos, dist
from pathlib import Path
from random import Random

from backend import career, cs2_maps, database, match, native_match_state


def obeys(actor, issued):
    goal, duty, expected = actor[15], actor[16], actor[22]
    if not goal:
        return False
    if duty and duty[1] >= issued and expected and dist(goal, expected) < 6:
        return True
    return (
        actor[1] == "T"
        and actor[26] >= issued
        and (not expected or dist(goal, expected) < 6)
    )


def run(name, seed, leg, output):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rids = Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    domain = database.match_input(pack, rids)
    first = domain["rosters"][rids[leg]]["team"]
    w = match.initial(seed, domain, rids, map_id=name, first_attack=first)
    w["autonomous"] = True
    owner = native_match_state.open_game(w)
    baseline = {a["id"]: a["mind"] for a in w["agents"]}
    resistance = {
        a["id"]: domain["players"][a["playerId"]]["skills"]["stress_resistance"]
        for a in w["agents"]
    }
    teams_by_player = {a["id"]: a["teamId"] for a in w["agents"]}
    tilt_path = []
    stalled_since = {}
    counts, phases, recovery = Counter(), Counter(), Counter()
    behavior, waits, suspected = Counter(), Counter(), Counter()
    extrema = {k: [100, 0] for k in ("stress", "confidence", "frustration")}
    plateaus, examples, calls, signals = {}, [], [], []
    old_order, prior, pending, previous_mind = {}, {}, {}, {}
    sent, close, tilt, tilt_rounds = {}, {}, {}, set()
    replay = []
    checkpoints = 0
    previous_round = 0
    last_tick = 0
    while True:
        frames = json.loads(owner.review_ticks(256))
        if not frames:
            break
        for f in frames:
            tick, rnd, phase = f["tick"], f["round"], f["phase"]
            last_tick = tick
            if rnd != previous_round:
                old_order.clear()
                prior.clear()
                plateaus.clear()
                pending.clear()
                sent.clear()
                close.clear()
                stalled_since.clear()
                first_live_tick = None
                previous_round = rnd
            for side, sender, who, x, y, z, due, carrier, size in f.get("sent", ()):
                sent[side, who, tick, sender] = due
                if carrier and size >= 3:
                    counts["groupCarrierPackets"] += 1
            if "actors" not in f:
                continue
            if first_live_tick is None:
                first_live_tick = tick
            live = {r[0]: r for r in f["actors"]}
            for side in ("CT", "T"):
                if side not in f:
                    continue
                p = f[side]
                at = defaultdict(set)
                carrier = None
                for (
                    who,
                    observed,
                    x,
                    y,
                    z,
                    source,
                    device,
                    sender,
                    place,
                    approach,
                ) in p["known"]:
                    if not place:
                        continue
                    if source == "Радио" and (side, who, observed, sender) in sent:
                        at[place].add(who)
                        if device:
                            carrier = place
                strong = next(
                    (
                        site
                        for site, contacts in at.items()
                        if len(contacts) >= 3 and (side == "T" or carrier == site)
                    ),
                    None,
                )
                key = (p["choice"], p["site"], p["revision"], p["issued"])
                if strong and (side, strong) not in close:
                    close[side, strong] = tick
                    signals.append(
                        dict(
                            round=rnd,
                            side=side,
                            tick=tick,
                            site=strong,
                            unique=len(at[strong]),
                            before=old_order.get(side),
                            after=key,
                            scores=p.get("scores"),
                            firstExecuted=None,
                            reports=[r for r in p["known"] if r[8] == strong],
                            due=[
                                sent.get((side, r[0], r[1], r[7]))
                                for r in p["known"]
                                if r[8] == strong
                            ],
                        )
                    )
                if side in old_order and key != old_order[side]:
                    counts[side + "Revisions"] += 1
                    old_live = {
                        k: tuple(r[2:5]) for k, r in live.items() if r[1] == side
                    }
                    pending[side] = (tick, key, old_live)
                old_order[side] = key
                if side in pending:
                    issued, current, positions = pending[side]
                    moved = [
                        pid
                        for pid, pos in positions.items()
                        if pid in live
                        and dist(live[pid][2:5], pos) > 0.5
                        and live[pid][6] == "assignment"
                        and obeys(live[pid], issued)
                    ]
                    if moved:
                        calls.append(
                            [side, rnd, issued, tick - issued, current, list(moved)]
                        )
                        pending.pop(side)
                for sig in reversed(signals[-2:]):
                    if (
                        sig["round"] != rnd
                        or sig["side"] != side
                        or sig["firstExecuted"] is not None
                    ):
                        continue
                    for pid, r in live.items():
                        if pid not in prior or r[1] != side:
                            continue
                        if side == "CT" and (not r[16] or r[16][0] != sig["site"]):
                            continue
                        if side == "T" and p["site"] == sig["site"]:
                            continue
                        if (
                            r[6] == "assignment"
                            and obeys(r, p["issued"])
                            and dist(r[2:5], prior[pid][2:5]) > 0.5
                        ):
                            sig["firstExecuted"] = [tick, p["choice"], pid, r[5], r[15]]
                            break
            for pid, r in live.items():
                side = r[1]
                pos = r[2:5]
                status = r[5]
                intent = r[6]
                goal = r[15]
                stress, confidence, frustration, focus = r[11:15]
                phases[side + "/" + phase] += 1
                if phase == "live":
                    phases[
                        side
                        + ("/opening" if tick - first_live_tick < 100 else "/midround")
                    ] += 1
                for k, val in zip(extrema, (stress, confidence, frustration)):
                    extrema[k] = [min(extrema[k][0], val), max(extrema[k][1], val)]
                state = frustration >= 48 and focus < -6
                if state:
                    tilt_rounds.add((rnd, pid))
                if state != tilt.get(pid, False):
                    tilt_path.append(
                        [rnd, tick, pid, state, stress, confidence, frustration]
                    )
                if state and not tilt.get(pid):
                    counts["tiltOnsets"] += 1
                if not state and tilt.get(pid):
                    counts["tiltRecoveries"] += 1
                tilt[pid] = state
                group = (
                    "resilient"
                    if resistance[pid] >= 70
                    else "sensitive" if resistance[pid] <= 45 else "middle"
                )
                if previous_mind.get(pid) != (stress, confidence, frustration):
                    if pid in previous_mind:
                        recovery[group + "/changes"] += 1
                        recovery[group + "/stressRise"] += max(
                            0, stress - previous_mind[pid][0]
                        )
                    previous_mind[pid] = (stress, confidence, frustration)
                if r[7]:
                    behavior[
                        group + ("/tilt/" if state else "/ordinary/") + intent
                    ] += 1
                old = prior.get(pid)
                if not old or dist(pos, old[2:5]) > 0.25:
                    plateaus[pid] = tick
                action, requested = f.get("actions", {}).get(pid, (None, None))
                still = tick - plateaus.get(pid, tick)
                travel_pending = (
                    requested
                    and dist(pos, requested) > 8
                    and intent == "assignment"
                    and not r[7]
                    and r[8] <= tick
                    and r[19] <= tick
                )
                if not travel_pending or not old or dist(pos, old[2:5]) > 0.25:
                    stalled_since.pop(pid, None)
                if travel_pending:
                    stalled_since.setdefault(pid, tick)
                if still >= 40:
                    waits[side + "/" + phase + "/" + status] += 1
                    # Require evidence of a broken precondition or an outstanding travel task.
                    # A deadline/ack by itself does not make a stationary angle ineffective.
                    reason = None
                    if requested and dist(pos, requested) <= 5:
                        counts["stationaryAtRequestedGoal"] += 1
                    if r[22] and dist(pos, r[22]) <= 6:
                        counts["stationaryAtAssignment"] += 1
                    if r[7] or r[8] > tick or r[19] > tick:
                        counts["stationaryEngaged"] += 1
                    duty = r[17]
                    covering = False
                    if (
                        duty
                        and duty[3]
                        and duty[4] == tick
                        and duty[2] == "executing"
                        and duty[1] >= tick
                    ):
                        bearing = atan2(duty[3][1] - pos[1], duty[3][0] - pos[0])
                        covering = cos(bearing - r[10]) > 0.9
                        if covering and duty[0] not in live:
                            counts["confirmedSectorTakeovers"] += 1
                    if (
                        duty
                        and not covering
                        and (duty[0] not in live or duty[1] < tick)
                    ):
                        reason = "group_unavailable"
                    if (
                        status.startswith(
                            (
                                "Ждёт готовности выхода",
                                "Ждёт страховку",
                                "Ждёт напарника на ретейке",
                            )
                        )
                        and old
                        and old[5] == status
                        and r[23]
                        and r[23] not in live
                        and r[23] not in prior
                    ):
                        reason = "absent_partner"
                    if (
                        tick - stalled_since.get(pid, tick) >= 35
                        and requested
                        and dist(pos, requested) > 8
                        and intent == "assignment"
                        and not r[7]
                        and r[8] <= tick
                        and r[19] <= tick
                        and any(
                            x in status
                            for x in (
                                "Занимает",
                                "Выход на",
                                "Перестраивается",
                                "Перетягивается",
                                "Сближается",
                                "Перегруппировка",
                                "Движется",
                                "Отходит",
                                "Меняет плент",
                            )
                        )
                    ):
                        reason = "no_travel_progress"
                    if reason:
                        suspected[side + "/" + reason + "/" + status] += 1
                        if len(examples) < 24 and not any(
                            e["player"] == pid
                            and e["round"] == rnd
                            and e["status"] == status
                            for e in examples
                        ):
                            examples.append(
                                dict(
                                    tick=tick,
                                    round=rnd,
                                    phase=phase,
                                    player=pid,
                                    status=status,
                                    reason=reason,
                                    pos=pos,
                                    goal=requested,
                                    action=action,
                                    blocked=r[9],
                                    expected=r[22],
                                    duty=r[16],
                                    group=r[17],
                                )
                            )
            if prior:
                counts["partnerLosses"] += len(prior.keys() - live.keys())
                counts["releasedGroupDuties"] += sum(
                    bool(prior[pid][17]) and not r[17]
                    for pid, r in live.items()
                    if pid in prior
                )
            prior = live
        if frames[-1]["phase"] == "finished":
            break
        # Replay an ordinary checkpoint with identical RNG and one changed player's
        # transient state. Keep the recorded match and its future completely independent.
        if (
            checkpoints < 5
            and leg == 0
            and rnd % 3 == 1
            and prior
            and any(r[7] for r in prior.values())
        ):
            saved = json.loads(owner.snapshot())
            if saved["phase"] in ("live", "planted"):
                candidates = [
                    a
                    for a in saved["agents"]
                    if a["hp"] and a["visible"] and a["mind"] != baseline[a["id"]]
                ]
                if candidates:
                    subject = max(
                        candidates,
                        key=lambda a: abs(
                            a["mind"]["focus"] - baseline[a["id"]]["focus"]
                        ),
                    )
                    checkpoints += 1
                    pid = subject["id"]
                    pair = []
                    for mind in (subject["mind"], baseline[pid]):
                        subject["mind"] = mind
                        clone = native_match_state.open_game(saved)
                        clone.advance(6)
                        output_state = json.loads(clone.snapshot())
                        actual = next(
                            a for a in output_state["agents"] if a["id"] == pid
                        )
                        pair.append(
                            [
                                actual["decision"]["intent"],
                                *[actual[k] for k in ("x", "y", "z", "lastShot", "hp")],
                            ]
                        )
                    replay.append(
                        dict(
                            round=rnd,
                            tick=saved["tick"],
                            actor=pid,
                            actual=pair[0],
                            neutral=pair[1],
                        )
                    )

    end = json.loads(owner.snapshot())
    assert end["phase"] == "finished" and last_tick < 150000
    tilt_wins = sum(
        end["history"][rnd - 1]["winnerTeamId"] == teams_by_player[pid]
        for rnd, pid in tilt_rounds
    )
    report = dict(
        tiltWins=tilt_wins,
        tiltPath=tilt_path,
        staff=w["coaches"],
        map=name,
        seed=seed,
        leg=leg,
        rosters=rids,
        first=first,
        score=end["score"],
        ticks=end["tick"],
        rounds=len(end["history"]),
        phases=phases,
        counts=counts,
        extrema=extrema,
        tiltPlayerRounds=len(tilt_rounds),
        recovery=recovery,
        behavior=behavior,
        stationary=waits,
        suspect=suspected,
        examples=examples,
        signals=signals,
        revisionsExecuted=len(calls),
        reactionExamples=calls[:12],
        timeouts=end["talkHistory"],
        coaches=end.get("breakDecisions", []),
        replay=replay,
        budget=[end["remaining"], end["rivalRemaining"]],
    )
    output.mkdir(exist_ok=True, parents=True)
    (output / f"{name}-{seed}-{leg}.json").write_text(
        json.dumps(report, ensure_ascii=False)
    )
    print(name, seed, leg, end["score"], counts, suspected, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--leg", type=int, choices=(0, 1), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.map, args.seed, args.leg, args.out)
