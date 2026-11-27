#include "agent_helpers.hpp"
#include "individual_decision.hpp"
#include <numbers>

namespace esport {
namespace {
constexpr std::array names{"assignment", "engage", "cover", "watch", "reload", "objective", "escape"};
const char *name(Choice choice) { return names[static_cast<size_t>(choice)]; }

// Only available reports compete for attention. A distant sound or an old radio
// report loses weight without consulting the current position of its subject.
int confidence(const Json &report, const Point &position, Tick now) {
    const Tick age = now - report.at("tick").get<Tick>();
    if (age < 0 || age >= 75)
        return 0;
    const int source = report.contains("confidence")     ? int(100 * report.at("confidence").get<double>())
                       : report.at("source") == "Зрение" ? 100
                       : report.at("source") == "Радио"  ? 82
                                                         : 65;
    const double range = distance(position, actor_point(report));
    return std::max(0, source - int(age) * 3 - int(std::min(100., range) / 4));
}

// Price only the actor's reports and static geometry. An unidentified sound has
// a direction but cannot be counted as another opponent.
ExecutionContext execution_context(AgentTurn &turn, const Situation &s, const Json &gun, const Json *focus,
                                   const Json &previous, bool new_task) {
    ExecutionContext x;
    const auto &a = turn.a;
    const auto now = turn.now;
    const auto pos = actor_point(a);
    if (!previous.empty()) {
        for (size_t i = 0; i < names.size(); ++i)
            if (previous.at("intent") == names[i])
                x.incumbent = static_cast<Choice>(i);
    }
    x.advancing = a.at("lastMove") == now - 1 && !a.value("blockedTicks", 0);
    x.under_fire = now - a.at("lastHurt").get<Tick>() <= 3 ||
                   (active(a, "incoming") && now - a.at("incoming").at("tick").get<Tick>() <= 3);
    x.changed = new_task || previous.empty() || previous.at("contacts") != s.contacts ||
                previous.value("threat", Json(nullptr)) !=
                    (focus ? focus->value("id", Json(nullptr)) : Json(nullptr));
    x.shots_needed = (100 + gun.at("damage").get<int>() - 1) / gun.at("damage").get<int>() + 1;
    x.gained_rounds = std::min(s.reserve, s.magazine - s.ammo);
    x.reload_duration = gun.at("reload");
    x.bullets_per_reload =
        (x.reload_duration + gun.at("interval").get<int>() - 1) / gun.at("interval").get<int>();
    x.continuing_reload = s.ammo > 0 && s.reload_ticks > 0;
    x.can_draw_loaded_gun = x.continuing_reload && s.reload_ticks > gun.at("interval").get<int>();
    if (s.carrying || (turn.side == "CT" && turn.w.at("phase") == "planted"))
        x.objective_ticks = turn.cfg.at("rules").at(s.carrying            ? "plant"
                                                    : a.at("kit") == true ? "kitDefuse"
                                                                          : "defuse");
    bool has_cover = active(a, "shelter");
    if (has_cover) {
        const auto &q = a.at("shelter");
        const double remaining = turn.grid ? gap2(xy(a), q.get<XY>()) : distance(pos, q.get<Point>());
        x.finishing_cover = x.incumbent == Choice::cover && !new_task && x.advancing && remaining > 1 &&
                            s.confidence > 15 && s.time_left > x.objective_ticks + 12;
        x.protected_cover = x.incumbent == Choice::cover && !s.contacts && !new_task && remaining <= 2.5 &&
                            s.confidence >= 40 && s.time_left > x.objective_ticks + 12;
        x.route_cost = std::min(12, int(remaining / 2));
    } else if (now < a.value("coverReview", Tick{0}) && !x.changed)
        x.route_available = false; // Last search found no reachable shelter.
    if (auto interrupted = a.find("lastReloadBreak"); interrupted != a.end() && !s.contacts &&
        a.at("weapon") == interrupted->at("weapon") && s.ammo == interrupted->at("ammo") &&
        a.at("lastShot") <= interrupted->at("tick") &&
        distance(pos, interrupted->at("position").get<Point>()) < 5) {
        x.unsafe_reload_window = s.ammo >= x.shots_needed || interrupted->value("repeated", false) ||
                                 now - interrupted->at("tick").get<Tick>() < x.reload_duration ||
                                 (focus && focus->value("id", Json(nullptr)) == interrupted->at("threat") &&
                                  s.confidence >= 35);
    }
    if (!focus)
        return x;
    x.tracking = !s.contacts && !new_task && !x.under_fire && s.remembered && x.incumbent == Choice::engage &&
                 a.at("target").is_string() && focus->value("id", Json(nullptr)) == a.at("target") &&
                 focus->at("source") == "Зрение" && now - focus->at("tick").get<Tick>() <= 3 && s.ammo &&
                 !s.reload_ticks && s.interaction_left < 0 && s.time_left > x.objective_ticks + 6;
    auto q = actor_point(*focus);
    double bearing = heading_gap(pos, q);
    x.proximity = std::clamp(100 - int(distance(pos, q)), 0, 100);
    for (const auto &r : a.at("knowledge")) {
        if (&r == focus || !r.contains("id") || !visual(r))
            continue;
        int weight = confidence(r, pos, now);
        x.other_contacts += weight / 12;
        x.crossfire = std::max(x.crossfire,
                               int((1 - std::cos(heading_gap(pos, actor_point(r)) - bearing)) * weight / 10));
    }
    if (focus->contains("weapon") && focus->at("weapon").is_string()) {
        const auto &weapons = turn.cfg.at("weapons");
        auto spec = weapons.find(focus->at("weapon").get<std::string>());
        if (spec != weapons.end()) {
            double facing = focus->contains("bodySector")
                                ? (1 + std::cos(heading_gap(q, pos) - focus->at("bodySector").get<double>() *
                                                                          std::numbers::pi / 4)) /
                                      2
                                : .5;
            x.incoming_damage =
                int(spec->at("damage").get<double>() * facing * s.confidence / (3 * std::max(20, s.hp)));
        }
    }
    if (!s.contacts &&
        (x.continuing_reload || (s.reserve > 0 && s.ammo < x.shots_needed + x.bullets_per_reload)))
        x.exposed_lane = turn.grid ? turn.grid->clear(xy(a), xy(*focus))
                                   : !turn.arena.objectives().map().hit(pos, q, 1, 64, 64);
    // At normal running pace an observed opponent can close this much space while
    // the magazine is out. Fresh reports on an open lane rule out a voluntary top-up.
    x.unsafe_reload_window |= x.exposed_lane && visual(*focus) &&
                             now - focus->at("tick").get<Tick>() < x.reload_duration &&
                             distance(pos, q) < 2 * move_speed(turn.player) * x.reload_duration;
    return x;
}

Json grid_cover(AgentTurn &turn, const Json &contact) {
    auto &a = turn.a;
    const auto &map = *turn.grid;
    const auto origin = xy(a), threat = xy(contact);
    if (turn.now >= a.value("coverReview", Tick{0})) {
        a["coverReview"] = turn.now + 8;
        a["shelter"] = nullptr;
        std::vector<std::pair<double, Cell>> candidates;
        for (const auto &cell : map.data.at("floor")) {
            const auto p = cell.get<Cell>();
            const auto q = map.center(p);
            const double d = gap2(origin, q);
            if (d <= 3 * map.unit && !map.clear(threat, q))
                candidates.emplace_back(d, p);
        }
        std::sort(candidates.begin(), candidates.end());
        for (const auto &[d, cell] : candidates) {
            if (cell == map.cell(origin) || !map.route(map.cell(origin), cell).empty()) {
                a["shelter"] = map.point(cell);
                break;
            }
        }
    }
    if (!active(a, "shelter") || map.clear(threat, a.at("shelter").get<XY>()))
        return nullptr;
    a["status"] = "Уходит за укрытие";
    bool moved = map.walk(a, a.at("shelter"), 2 * move_speed(turn.player), turn.grid_fire, true);
    return Json::array({moved ? "move" : "hold", nullptr});
}
} // namespace

Json AgentTurn::personal_decision() {
    if (!grid && a.value("lastBlockedTick", Tick{-1000}) != now - 1)
        a["blockedTicks"] = 0;
    service_weapon();
    auto contact = select_contact();
    const bool using_device = !action.empty() && action.at("player") == a.at("id");
    const bool planted = w.at("phase") == "planted";
    const bool carrying = !device.empty() && device.at("carrier") == a.at("id");
    Json escape;
    if (planted && !using_device) {
        if (!grid && side == "CT" && !action.empty() && !device.empty() && gap(device) < 45)
            a.erase("saving");
        escape = a.value("saving", Json(nullptr));
        if (escape.empty())
            escape = grid ? grid_exit() : saved_exit();
    }
    const auto &gun = cfg.at("weapons").at(a.at("weapon").get<std::string>());
    const auto pos = actor_point(a);
    const auto hurt = a.at("lastHurt").get<Tick>();
    if (a.at("reloadAt") > now && hurt == now - 1)
        a["exposedReload"] = {{"position", pos}, {"tick", hurt}};
    int reload_exposure = 0;
    if (auto memory = a.find("exposedReload"); memory != a.end()) {
        const auto age = now - memory->at("tick").get<Tick>();
        const double d = distance(pos, memory->at("position").get<Point>());
        if (age < 1200 && d < 30)
            reload_exposure = int((1 - d / 30) * (1 - age / 1200.) * 40);
    }
    int certainty = 0;
    Point focus{};
    const Json *report_focus = nullptr;
    for (const auto &report : a.at("knowledge")) {
        const int strength = confidence(report, pos, now);
        if (strength > certainty) {
            certainty = strength;
            focus = actor_point(report);
            report_focus = &report;
        }
    }
    auto site = plan.at("site").get<std::string>();
    if (side == "CT") {
        if (!grid)
            site = assignment(plan, a, squad).at("site");
        else if (slot != 4)
            site = slot % 2 == 0 ? "A" : "B";
        if (planted && !a.at("heardSite").empty())
            site = a.at("heardSite");
        else if (planted && !plan.at("reinforce").empty())
            site = plan.at("reinforce");
    }
    const bool board = active(plan, "board") && !planted && !active(plan, "rotated") &&
                       step_index < int(plan.at("board").at("slots").at(slot).size());
    const bool recovering = !recovery.empty() && recovery.at("player") == a.at("id");
    const auto role = a.at("playingRole").get<std::string>();
    const auto map = grid ? std::string("depo") : w.at("mapId").get<std::string>().substr(3);
    const Situation situation{
        .contacts = int(a.at("visible").size()),
        .hp = a.at("hp"),
        .ammo = a.at("ammo"),
        .magazine = gun.at("mag"),
        .reserve = a.at("reserve"),
        .reload_ticks = int(std::max<Tick>(0, a.at("reloadAt").get<Tick>() - now)),
        .time_left = int(w.at("deadline").get<Tick>() - now),
        .interaction_left = using_device ? int(action.at("end").get<Tick>() - now) : -1,
        .aggression = skills.at("aggression"),
        .risk = skills.at("risk"),
        .discipline = skills.at("discipline"),
        .reading = skills.at("game_reading"),
        .familiarity = player.at("mapKnowledge").value(map, 0),
        .role_experience = player.at("roleMastery").value(role, 0),
        .entry = role == "entry",
        .support = role == "support",
        .committed = board || planted || recovering,
        .carrying = carrying,
        .can_escape = !escape.empty(),
        .remembered = certainty > 0 && a.at("blind") <= now,
        .recent_damage = now - a.at("lastHurt").get<Tick>() < 12,
        .reload_exposure = reload_exposure,
        .confidence = certainty,
    };
    const char *goal =
        planted ? (side == "CT" ? "retake" : "postplant") : (side == "CT" ? "defend" : "attack");
    const char *task = recovering ? "recover" : board ? "board" : carrying ? "carry" : "order";
    const int step = board ? step_index : -1;
    const Json empty;
    const auto previous = a.find("decision");
    const auto &mind = previous == a.end() ? empty : *previous;
    const bool revised = w.at("agentPolicy") == 2;
    const bool new_task = mind.empty() || mind.at("goal") != goal || mind.at("site") != site ||
                          mind.at("task") != task || mind.at("step") != step;
    const Json threat = revised && report_focus ? report_focus->value("id", Json(nullptr)) : Json(nullptr);
    const Tick since = revised && !new_task ? mind.value("since", now) : now;
    ExecutionContext execution;
    if (revised) {
        execution = execution_context(*this, situation, gun, report_focus, mind, new_task);
        if (execution.changed && !contact.empty() && active(a, "shelter")) {
            const auto &q = a.at("shelter");
            bool exposed =
                grid ? grid->clear(xy(contact), q.get<XY>())
                     : !arena.objectives().map().hit(actor_point(contact), q.get<Point>(), 1, 64, 64);
            if (exposed) {
                a["shelter"] = nullptr;
                a["coverReview"] = now;
                execution.finishing_cover = execution.protected_cover = false;
            }
        }
    }
    auto options = alternatives(situation, revised ? &execution : nullptr);
    Json intent;
    Choice chosen = Choice::assignment;
    for (auto &candidate : options) {
        if (!candidate.available)
            break;
        chosen = candidate.choice;
        switch (chosen) {
        case Choice::escape: {
            a["saving"] = escape;
            a["status"] = side == "T" ? "Отходит от C4" : "Сохраняет оружие";
            bool moved =
                grid ? grid->walk(a, escape, 2 * move_speed(player), grid_fire, true) : move(escape, 2);
            if (!moved && !contact.empty()) {
                candidate.reachable = false;
                continue;
            }
            intent = Json::array({moved ? "move" : "hold", nullptr});
            break;
        }
        case Choice::cover:
            if (revised && execution.protected_cover) {
                heading_to(a, focus);
                a["status"] = "Наблюдает из укрытия";
                intent = Json::array({"hold", nullptr});
            } else if (revised && execution.finishing_cover && contact.empty()) {
                a["status"] = "Уходит за укрытие";
                bool moved = grid ? grid->walk(a, a.at("shelter"), 2 * move_speed(player), grid_fire, true)
                                  : move(a.at("shelter").get<Point>(), 2);
                if (!moved && a.value("blockedTicks", 0)) {
                    a.erase("shelter");
                    candidate.reachable = false;
                    continue;
                }
                intent = Json::array({moved ? "move" : "hold", nullptr});
            } else
                intent = grid ? grid_cover(*this, contact) : seek_cover(contact, true);
            if (intent.is_null()) {
                candidate.reachable = false;
                continue;
            }
            break;
        case Choice::engage:
            if (revised && execution.can_draw_loaded_gun) {
                a["reloadAt"] = 0;
                // A second failed top-up with the same cartridges at the same corner
                // requires a change of position or actual expenditure before another try.
                auto prior = a.find("lastReloadBreak");
                bool repeated = prior != a.end() && prior->at("weapon") == a.at("weapon") &&
                                prior->at("ammo") == situation.ammo &&
                                a.at("lastShot") <= prior->at("tick") &&
                                distance(pos, prior->at("position").get<Point>()) < 5;
                a["lastReloadBreak"] = {{"tick", now}, {"position", pos}, {"weapon", a.at("weapon")},
                                        {"threat", contact.at("id")}, {"ammo", situation.ammo}, {"repeated", repeated}};
            }
            if (revised && execution.tracking) {
                if (!grid)
                    intent = last_burst();
                if (intent.empty()) {
                    heading_to(a, focus);
                    a["status"] = "Держит последний угол контакта";
                    intent = Json::array({"hold", nullptr});
                }
            } else
                intent = duel(contact);
            break;
        case Choice::reload:
            if (!revised || !execution.continuing_reload)
                a["reloadAt"] = now + gun.at("reload").get<int>();
            a["status"] = "Пополняет магазин в паузе";
            intent = Json::array({"hold", nullptr});
            break;
        case Choice::watch:
            heading_to(a, focus);
            a["status"] = "Проверяет направление последнего контакта";
            intent = Json::array({"hold", nullptr});
            break;
        case Choice::objective:
            intent = Json::array({"objective", nullptr});
            break;
        case Choice::assignment:
            if (!grid)
                intent = last_burst();
            break;
        case Choice::count:
            break;
        }
        break;
    }
    if (!(revised && execution.tracking && chosen == Choice::engage) && contact.empty() &&
        (intent.empty() || intent.at(0) != "shoot"))
        a["target"] = nullptr;

    // The checkpoint keeps one deliberation per player. Refresh on a change of
    // task, choice, or on the personal review interval. Match-center statuses
    // come from the actual executor.
    auto &snapshot = a["decision"];
    if ((revised && execution.changed) || snapshot.empty() || snapshot.at("intent") != name(chosen) ||
        snapshot.at("goal") != goal || snapshot.at("task") != task || snapshot.at("site") != site ||
        snapshot.at("step") != step || now - snapshot.at("tick").get<Tick>() >= 12) {
        Json scores = Json::object();
        for (const auto &option : options)
            if (option.available)
                scores[name(option.choice)] = {
                    {"benefit", option.benefit}, {"risk", option.risk}, {"reachable", option.reachable}};
        snapshot = {{"tick", now},
                    {"goal", goal},
                    {"task", task},
                    {"site", site},
                    {"step", step},
                    {"intent", name(chosen)},
                    {"contacts", situation.contacts},
                    {"confidence", certainty},
                    {"reloadExposure", reload_exposure},
                    {"alternatives", std::move(scores)}};
        if (revised) {
            snapshot["since"] = execution.incumbent == chosen ? since : now;
            snapshot["threat"] = threat;
            for (const auto &option : options)
                if (option.available)
                    snapshot["alternatives"][name(option.choice)]["continuity"] = option.continuity;
        }
    }
    return intent;
}
} // namespace esport
