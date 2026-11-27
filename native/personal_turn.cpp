#include "agent_helpers.hpp"
#include "individual_decision.hpp"

namespace esport {
namespace {
constexpr std::array names{"assignment", "engage", "cover", "watch", "reload", "objective", "escape"};
const char *name(Choice choice) { return names[static_cast<size_t>(choice)]; }

// Only available reports compete for attention. A distant sound or an old radio report
// loses weight without consulting the current position of its subject.
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
    for (const auto &report : a.at("knowledge")) {
        const int strength = confidence(report, pos, now);
        if (strength > certainty) {
            certainty = strength;
            focus = actor_point(report);
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
    auto options = alternatives(situation);
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
            intent = grid ? grid_cover(*this, contact) : seek_cover(contact, true);
            if (intent.is_null()) {
                candidate.reachable = false;
                continue;
            }
            break;
        case Choice::engage:
            intent = duel(contact);
            break;
        case Choice::reload:
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
    if (contact.empty() && (intent.empty() || intent.at(0) != "shoot"))
        a["target"] = nullptr;

    // The checkpoint keeps one deliberation per player. Refresh on a change of task, choice,
    // or on the personal review interval. Match-center statuses come from the actual executor.
    const char *goal =
        planted ? (side == "CT" ? "retake" : "postplant") : (side == "CT" ? "defend" : "attack");
    const char *task = recovering ? "recover" : board ? "board" : carrying ? "carry" : "order";
    const int step = board ? step_index : -1;
    auto &mind = a["decision"];
    if (mind.empty() || mind.at("intent") != name(chosen) || mind.at("goal") != goal ||
        mind.at("task") != task || mind.at("site") != site || mind.at("step") != step ||
        now - mind.at("tick").get<Tick>() >= 12) {
        Json scores = Json::object();
        for (const auto &option : options)
            if (option.available)
                scores[name(option.choice)] = {
                    {"benefit", option.benefit}, {"risk", option.risk}, {"reachable", option.reachable}};
        mind = {{"tick", now},
                {"goal", goal},
                {"task", task},
                {"site", site},
                {"step", step},
                {"intent", name(chosen)},
                {"contacts", situation.contacts},
                {"confidence", certainty},
                {"reloadExposure", reload_exposure},
                {"alternatives", std::move(scores)}};
    }
    return intent;
}
} // namespace esport
