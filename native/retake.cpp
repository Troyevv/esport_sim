#include "tactic_execution.hpp"
#include "team_ai.hpp"
#include <algorithm>
#include <cmath>

namespace esport {
namespace {
Json path_length(const Point &origin, const WalkPath &path) {
    auto p = origin;
    double length = 0;
    for (auto &[x, y, z, zone] : path) {
        Point q{x, y, z};
        length += distance(p, q);
        p = q;
    }
    return path.empty() ? Json(0) : Json(length);
}
Json approach(const PhysicalNavigation &nav, const Json &actor, const Point &center,
              std::optional<Point> via = {}) {
    auto origin = actor_point(actor), goal = via.value_or(center);
    auto to = nav.locate(goal), site = nav.locate(center);
    if (!to || !site)
        return nullptr;
    auto path = nav.path(actor.at("navArea"), origin, *to, goal, {});
    if (!path)
        return nullptr;
    if (via) {
        auto tail = nav.path(*to, *via, *site, center, {});
        if (!tail)
            return nullptr;
        path->insert(path->end(), tail->begin(), tail->end());
    }
    auto entry = origin;
    for (auto it = path->rbegin(); it != path->rend(); ++it) {
        Point q{std::get<0>(*it), std::get<1>(*it), std::get<2>(*it)};
        if (distance(q, center) >= 23) {
            entry = q;
            break;
        }
    }
    auto stage = via.value_or(entry);
    auto from = nav.locate(stage);
    if (!from)
        return nullptr;
    auto tail = nav.path(*from, stage, *site, center, {});
    if (!tail)
        return nullptr;
    return Json{{"stage", stage},
                {"entry", entry},
                {"length", path_length(origin, *path)},
                {"tail", path_length(stage, *tail)}};
}
} // namespace
void assemble_retake(Json &w, const Json &cfg, const OpeningMap &arena, const Squad &squad,
                     const Json &leader, const std::string &site) {
    auto center = arena.site_point(site);
    auto device = leader.value("seenDevice", Json(nullptr));
    if (!device.empty() && device.at("site") == site)
        center = actor_point(device);
    Tick now = w.at("tick"), deadline = w.at("deadline");
    auto &nav = arena.objectives().map();
    const auto &captain = player_profile(w, leader).at("skills");
    Json duties = Json::object(), direct = Json::object();
    Squad order;
    for (auto p : squad)
        if (!p->contains("saving") || p->at("saving").empty()) {
            auto route = approach(nav, *p, center);
            if (!route.is_null()) {
                direct[p->at("id").get<std::string>()] = std::move(route);
                order.push_back(p);
            }
        }
    auto id = [](const Json *a) { return a->at("id").get<std::string>(); };
    std::stable_sort(order.begin(), order.end(), [&](auto a, auto b) {
        return direct.at(id(a)).at("length") < direct.at(id(b)).at("length");
    });
    for (auto p : order) {
        auto route = direct.at(id(p));
        const auto &player = player_profile(w, *p), &skills = player.at("skills");
        double pace = 2 * move_speed(player);
        int use = cfg.at("rules").at(p->at("kit") == true ? "kitDefuse" : "defuse");
        double slack = deadline - now - use - route.at("length").get<double>() / pace;
        auto close = [&](const Point &q) {
            return std::ranges::any_of(
                duties, [&](const Json &d) { return distance(q, d.at("entry").get<Point>()) < 20; });
        };
        if (!duties.empty() && slack > 40 && close(route.at("entry")) && route.at("length") > 35) {
            std::set<std::string> labels;
            for (auto &z : arena.profile().at("guards").at(site))
                labels.insert(z);
            for (auto &z : arena.profile().at(site))
                labels.insert(z.back());
            std::set<Point> points;
            for (auto &label : labels)
                for (auto area : arena.layout().places.at(label))
                    points.insert(nav.center(area));
            std::vector<Point> ordered(points.begin(), points.end());
            auto cost = [&](const Point &pnt) {
                return distance(actor_point(*p), pnt) + distance(pnt, center);
            };
            std::stable_sort(ordered.begin(), ordered.end(),
                             [&](auto &a, auto &b) { return cost(a) < cost(b); });
            Json best = nullptr;
            for (auto &q : ordered) {
                auto gap = distance(q, center);
                if (gap <= 16 || gap >= 75)
                    continue;
                auto alternative = approach(nav, *p, center, q);
                if (alternative.empty() || close(alternative.at("entry")))
                    continue;
                double extra =
                    (alternative.at("length").get<double>() - route.at("length").get<double>()) / pace;
                auto familiarity =
                    player.at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0);
                if (extra <= std::min(slack - 35, (familiarity + skills.at("timing").get<int>() +
                                                   captain.at("calling").get<int>()) /
                                                      5.) &&
                    (best.is_null() || alternative.at("length") < best.at("length")))
                    best = std::move(alternative);
            }
            if (!best.is_null())
                route = std::move(best);
        }
        double eta = std::max(0., route.at("length").get<double>() - route.at("tail").get<double>()) / pace;
        Tick due = deadline - use - Tick(std::nearbyint(route.at("tail").get<double>() / pace)) - 20;
        if (slack > 20 && distance(actor_point(*p), center) > 18 && now + eta < due) {
            route["eta"] = Tick(std::nearbyint(now + eta));
            route["latest"] = due;
            duties[id(p)] = std::move(route);
        }
    }
    for (auto p : squad)
        if (duties.contains(id(p))) {
            auto &duty = duties.at(id(p));
            Json *best = nullptr;
            double cost = 0;
            for (auto m : squad)
                if (m != p && duties.contains(id(m))) {
                    auto diff =
                        std::abs(duties.at(id(m)).at("eta").get<Tick>() - duty.at("eta").get<Tick>()) -
                        chemistry(w, *m, *p) / 12.;
                    if (!best || diff < cost) {
                        best = m;
                        cost = diff;
                    }
                }
            if (best) {
                duty["partner"] = id(best);
                duty["release"] =
                    std::min({duty.at("latest").get<Tick>(), duties.at(id(best)).at("eta").get<Tick>(),
                              duty.at("eta").get<Tick>() + 6 +
                                  (captain.at("calling").get<int>() +
                                   player_profile(w, *p).at("skills").at("synchronization").get<int>()) /
                                      9});
            }
        }
    w.at("plans").at("CT")["retake"] = Json{{"site", site}, {"duties", duties}};
}
} // namespace esport
