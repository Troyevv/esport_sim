#include "agent_turn.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
namespace esport {
namespace {
double walk_length(Point origin, const WalkPath &route) {
    double length = 0;
    for (auto &[x, y, z, area] : route) {
        Point q{x, y, z};
        length += distance(origin, q);
        origin = q;
    }
    return length;
}
int equipment_value(const Json &a, const Json &cfg) {
    const auto &guns = cfg.at("weapons"), &prices = cfg.at("prices");
    int value = guns.at(a.at("weapon").get<std::string>()).at("price");
    if (!a.at("holster").empty())
        value += guns.at(a.at("holster").at("weapon").get<std::string>()).at("price").get<int>();
    if (a.at("armor") != 0)
        value += prices.at("Броня").get<int>();
    if (a.at("helmet") == true)
        value += prices.at("Шлем").get<int>();
    if (a.at("kit") == true)
        value += prices.at("Набор").get<int>();
    for (auto &g : a.at("utility"))
        value += prices.at(g.get<std::string>()).get<int>();
    return value;
}
} // namespace
Json AgentTurn::saved_exit() {
    Json site = device.empty() ? Json(nullptr) : device.at("site");
    if (site.is_null())
        site = a.at("heardSite");
    if (site.is_null())
        site = plan.at("reinforce");
    if (site.is_null())
        return nullptr;
    const Point pos = device.empty() ? arena.site_point(site) : actor_point(device), origin = actor_point(a);
    auto area = a.at("navArea").get<AreaId>();
    double blast = cfg.at("blastRadius");
    auto routes = nav.safe_routes(pos, blast + 4);
    auto cost = routes->cost(area);
    if (!cost)
        return nullptr;
    double speed = 2 * move_speed(player);
    int threats = 0;
    for (auto &r : a.at("knowledge"))
        if (r.at("source") != "Слух" && r.at("source") != "Граната" && now - r.at("tick").get<Tick>() < 32 &&
            distance(actor_point(r), pos) < 60)
            ++threats;
    Tick remaining = w.at("deadline").get<Tick>() - now;
    auto path_to = [&](const Point &goal) -> std::optional<WalkPath> {
        auto dest = nav.locate(goal);
        return dest ? nav.path(area, origin, *dest, goal, {}) : std::nullopt;
    };
    auto route = routes->route(area);
    if (!route)
        return nullptr;
    const auto zone = route->second.back();
    auto chosen = nav.center(zone);
    if (side == "T") {
        auto reserve = 12 + equipment_value(a, cfg) / 450. - threats * 3;
        auto departure = *cost / nav.unit() / speed + reserve;
        if (distance(origin, pos) < blast &&
            ((a.at("status") == "Прикрывает C4" && a.at("path").empty()) || remaining <= departure)) {
            auto planned = path_to(chosen);
            auto d = planned ? walk_length(origin, *planned) : std::numeric_limits<double>::infinity();
            if (d / speed > departure)
                if (auto alternative = nav.escape(area, origin, pos, blast + 4)) {
                    if (remaining > std::max(departure, alternative->first / speed + reserve))
                        return nullptr;
                    if (!alternative->second.empty()) {
                        auto [x, y, z, id] = alternative->second.back();
                        Point safe{x, y, z};
                        auto at = nav.locate(safe);
                        a["path"] = alternative->second;
                        a["dest"] = Json::array({at ? Json(*at) : Json(nullptr), x, y, z, Json::array()});
                        return safe;
                    }
                }
        }
        if (remaining > departure)
            return nullptr;
    } else {
        if (!action.empty())
            return nullptr;
        int use = cfg.at("rules").at(a.at("kit") == true ? "kitDefuse" : "defuse");
        if (!device.empty() && distance(origin, pos) <= 6 && clear(a, device) && remaining > use)
            return nullptr;
        Json floor;
        if (!device.empty()) {
            if (a.value("useTarget", Json(nullptr)) != pos || a.value("blockedTicks", 0) >= 5) {
                auto point = nav.use_position(area, origin, pos, 6);
                a["useFloor"] = point ? Json(*point) : Json(nullptr);
                a["useTarget"] = pos;
            }
            floor = a.value("useFloor", Json(nullptr));
        } else {
            floor = pos;
            if (a.contains("bombSearch") && !a.at("bombSearch").empty() &&
                !a.at("bombSearch").value("goal", Json(nullptr)).empty())
                floor = a.at("bombSearch").at("goal");
        }
        std::optional<WalkPath> path;
        double length = 0;
        if (!floor.empty()) {
            Point goal = floor;
            const auto &current = a.at("path");
            if (!current.empty() && Point{current.back()[0], current.back()[1], current.back()[2]} == goal)
                path = current.get<WalkPath>();
            else
                path = path_to(goal);
            if (path)
                length = walk_length(origin, *path);
        }
        if (path && length / speed + 12 < remaining && std::ranges::any_of(squad, [&](const Json *p) {
                return p != &a && p->at("kit") == true && p->value("saving", Json(nullptr)).empty() &&
                       !p->value("seenDevice", Json(nullptr)).empty() &&
                       distance(actor_point(*p), pos) < 12 &&
                       remaining > cfg.at("rules").at("kitDefuse").get<int>() + 6;
            }))
            return nullptr;
        double margin =
            std::min(50., length / 2) * (100 - skills.at("retakes").get<int>()) / 100 +
            (50 - skills.at("risk").get<int>()) * std::min(1., equipment_value(a, cfg) / 3000.) / 2;
        if (path && remaining > std::max(0., length - 6) / speed + use +
                                    std::max(0, threats - int(squad.size()) + 1) * 8 + (threats ? margin : 0))
            return nullptr;
    }
    if (nav.path(area, origin, zone, chosen, {}))
        return chosen;
    std::vector<Point> safe;
    for (auto &[id, p] : nav.centers()) {
        auto d = distance(p, pos);
        if (d < blast * 1.8 && d > blast + 2)
            safe.push_back(p);
    }
    std::stable_sort(safe.begin(), safe.end(),
                     [&](auto &l, auto &r) { return distance(origin, l) < distance(origin, r); });
    auto from = nav.locate(origin);
    if (from)
        for (auto &q : safe)
            if (auto to = nav.locate(q); to && nav.path(*from, origin, *to, q, {}))
                return q;
    return nullptr;
}

Json AgentTurn::contact_decision() {
    if (a.value("lastBlockedTick", Tick{-1000}) != now - 1)
        a["blockedTicks"] = 0;
    auto contact = select_contact();
    service_weapon();
    bool using_device = !action.empty() && action.at("player") == a.at("id");
    if (!contact.empty() && using_device &&
        action.at("end").get<Tick>() - now <=
            3 + skills.at("confidence").get<int>() / 10 + player.at("morale").get<int>() / 30)
        contact = nullptr;
    if (w.at("phase") == "planted" && !using_device) {
        if (side == "CT" && !action.empty() && !device.empty() && gap(device) < 45)
            a.erase("saving");
        auto goal = a.value("saving", Json(nullptr));
        if (goal.empty())
            goal = saved_exit();
        if (!goal.empty()) {
            a["saving"] = goal;
            a["status"] = side == "T" ? "Отходит от C4" : "Сохраняет оружие";
            if (move(goal, 2))
                return Json::array({"move", nullptr});
            if (contact.empty())
                return Json::array({"hold", nullptr});
        }
    }
    if (action.empty() && w.at("deadline").get<Tick>() - now > 35) {
        auto result = seek_cover(contact);
        if (!result.is_null())
            return result;
    }
    if (!contact.empty())
        return duel(contact);
    auto burst = last_burst();
    if (!burst.is_null())
        return burst;
    a["target"] = nullptr;
    if (using_device)
        return Json::array({"objective", nullptr});
    return nullptr;
}
} // namespace esport
