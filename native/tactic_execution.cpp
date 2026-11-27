#include "tactic_execution.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>

namespace esport {
namespace {
Point pos(const Json &p) { return {p.at("x"), p.at("y"), p.value("z", 0.)}; }

int execution_delay(const Json &w, const Json &a, const Json &player, const Json &board) {
    const auto &skills = player.at("skills");
    const std::string role = a.at("playingRole");
    int delay = 1 + (100 - skills.at("execution").get<int>()) / 20 +
                (100 - player.at("roleMastery").value(role, 0)) / 35;
    if (player.contains("tactics")) {
        auto key = board.at("id").get<std::string>() + "@" + board.at("revision").dump();
        auto map = board.at("map").get<std::string>();
        if (map.starts_with("de_"))
            map.erase(0, 3);
        int pairs = 0, count = 0;
        std::string id = a.at("playerId");
        for (const auto &mate : w.at("agents")) {
            if (mate.at("team") != a.at("team") || mate.at("hp") == 0 || mate.at("playerId") == id)
                continue;
            std::string other = mate.at("playerId");
            pairs += w.at("domain").at("chemistry").value(std::min(id, other) + "|" + std::max(id, other), 0);
            ++count;
        }
        double understanding = .65 * player.at("tactics").value(key, 0) +
                               .2 * player.at("mapKnowledge").value(map, 45) +
                               .15 * pairs / std::max(1, count);
        delay += static_cast<int>(std::nearbyint((50 - understanding) / 13));
    }
    return std::max(1, delay);
}
} // namespace

double move_speed(const Json &player) {
    const auto &s = player.at("skills");
    return .82 + s.at("movement").get<double>() * .003 -
           player.at("fatigue").get<double>() * (110 - s.at("fatigue_resistance").get<double>()) / 35000;
}

bool travel(Json &a, const Json &player, const PhysicalNavigation &map, const Point &goal, double pace,
            const std::vector<Hazard> &fire, Tick now) {
    const auto &dest = a.at("dest");
    std::optional<Destination> destination;
    if (dest.size() == 5 && !dest[0].is_null())
        destination = Destination{dest[0].get<AreaId>(), Point{dest[1], dest[2], dest[3]},
                                  dest[4].get<std::set<AreaId>>()};
    MotionState motion{pos(a),
                       a.at("navArea"),
                       a.at("heading"),
                       a.value("blockedTicks", 0),
                       a.at("path").get<WalkPath>(),
                       destination};
    auto result = map.walk(motion, goal, pace * move_speed(player), fire);
    a["blockedTicks"] = motion.blocked_ticks;
    if (result.replanned) {
        const auto &[zone, p, avoided] = motion.destination.value();
        a["dest"] = Json::array({zone, p[0], p[1], p[2], avoided});
        a["path"] = motion.path;
    } else if (result.consumed) {
        auto &path = a.at("path");
        path.erase(path.begin(), path.begin() + result.consumed);
    }
    if (result.moved) {
        a["x"] = motion.position[0];
        a["y"] = motion.position[1];
        a["z"] = motion.position[2];
        a["heading"] = motion.heading;
    }
    a["navArea"] = motion.area;
    if (result.waiting)
        a["status"] = "Пережидает огонь за укрытием";
    if (motion.blocked_ticks) {
        a["lastBlockedTick"] = now;
        a["blockedGoal"] = goal;
    }
    return result.moved;
}

Json board_step(Json &w, Json &a, const Json &cfg, const Objectives &objectives, const Json &bomb,
                const std::vector<Hazard> &fire) {
    const Tick now = w.at("tick");
    const int index = a.at("stepIndex");
    const auto &board = w.at("plans").at(a.at("team").get<std::string>()).at("board");
    const auto &steps = board.at("slots").at(a.at("slot").get<int>());
    const auto hold = Json::array({"hold", nullptr});
    if (now < a.at("stepReady").get<Tick>()) {
        a["status"] = "Готовит следующий шаг";
        return hold;
    }
    if (index < 0)
        throw std::invalid_argument("Недопустимый номер шага тактики");
    if (static_cast<std::size_t>(index) >= steps.size())
        return nullptr;
    const auto &step = steps.at(index);
    const std::string kind = step.at("kind");
    const auto goal = pos(step);
    const auto &player = w.at("domain").at("players").at(a.at("playerId").get<std::string>());
    a["status"] = cfg.at("boardLabels").at(kind).get<std::string>() + " · точка " + std::to_string(index + 1);
    if (kind != "throw" && kind != "face" && pos(a) != goal) {
        double pace = kind == "exit" || kind == "retreat" ? 2. : 1.;
        bool moved;
        if (auto grid = objectives.grid()) {
            Json hazards = Json::array();
            for (auto &[p, r] : fire)
                hazards.push_back(Json{{"x", p[0]}, {"y", p[1]}, {"radius", r}});
            moved = grid->walk(a, Json::array({step.at("x"), step.at("y")}), pace * move_speed(player),
                               hazards, true);
        } else
            moved = travel(a, player, objectives.map(), goal, pace, fire, now);
        if (!moved)
            return hold;
        if (kind == "retreat")
            a["heading"] = a.at("heading").get<double>() + std::numbers::pi;
        return Json::array({"move", nullptr});
    }
    if (kind == "face" || kind == "hold" || kind == "wait") {
        if (kind == "face")
            a["heading"] = std::atan2(goal[1] - a.at("y").get<double>(), goal[0] - a.at("x").get<double>());
        else if (kind == "hold")
            a["heading"] = (a.at("team") == "CT" ? std::numbers::pi : 0.) +
                           1.6 * std::sin((now + a.at("slot").get<int>() * 12) / 16.);
        if (a.at("stepUntil").is_null())
            a["stepUntil"] = plus_ticks(now, step.at("seconds").get<int>() * 10);
        if (now < a.at("stepUntil").get<Tick>())
            return hold;
    }
    a["stepIndex"] = index + 1;
    a["stepUntil"] = nullptr;
    Json intent = hold;
    if (kind == "plant" && !bomb.empty() && bomb.at("carrier") == a.at("id")) {
        const auto site = objectives.site_at(goal);
        intent = Json::array({"plant", site ? Json(*site) : Json(nullptr)});
    }
    if (kind == "throw") {
        const auto &inventory = a.at("utility");
        if (objectives.grid() && !objectives.grid()->clear(xy(a), {goal[0], goal[1]}))
            a["status"] = "Пропускает бросок · путь перекрыт";
        else if (std::find(inventory.begin(), inventory.end(), step.at("utility")) != inventory.end()) {
            if (now < a.at("throwAt").get<Tick>()) {
                a["stepIndex"] = index;
                return hold;
            }
            intent = Json::array({"throw", step});
        } else
            a["status"] = "Пропускает бросок · нет гранаты";
    }
    a["stepReady"] = plus_ticks(now, execution_delay(w, a, player, board));
    return intent;
}
} // namespace esport
