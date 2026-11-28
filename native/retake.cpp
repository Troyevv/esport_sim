#include "defense_route.hpp"
#include "grid_round.hpp"
#include "tactic_execution.hpp"
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
double route_resistance(const Json &world, const Json &cfg, const PhysicalNavigation &nav,
                        const Json &observer, Point start, const WalkPath &route, double speed) {
    const Tick now = world.at("tick");
    auto encounter = [&](const Point &point, double range, bool sight) {
        Point prev = start;
        double travel = 0.;
        for (auto &[x, y, z, area] : route) {
            Point q{x, y, z};
            double length = distance(prev, q);
            double along = 0;
            for (size_t i = 0; i < 3; ++i)
                along += (point[i] - prev[i]) * (q[i] - prev[i]);
            double fraction = std::clamp(along / std::max(.001, length * length), 0., 1.);
            Point nearest{};
            for (size_t i = 0; i < 3; ++i)
                nearest[i] = prev[i] + fraction * (q[i] - prev[i]);
            if (distance(nearest, point) < range && (!sight || !nav.hit(nearest, point, 1, 64, 64)))
                return (travel + length * fraction) / speed;
            travel += length;
            prev = q;
        }
        return 1e6;
    };
    double delay = 0, obstruction = 0;
    auto screen = [&](const Json &item, const Point &q, Tick end) {
        if ((item != "Дым" && item != "Огонь") || end <= now)
            return;
        auto at = encounter(q, cfg.at("utility").at(item.get<std::string>())[0], false);
        obstruction = std::max(obstruction, std::clamp(end - now - at, 0., item == "Огонь" ? 25. : 12.));
    };
    for (const auto &r : observer.at("knowledge")) {
        auto age = now - r.at("tick").get<Tick>();
        if (age < 0 || r.value("disputed", false))
            continue;
        if (r.contains("item") && r.at("source") == "Граната") {
            screen(r.at("item"), actor_point(r),
                   r.at("tick").get<Tick>() + (r.at("item") == "Дым" ? 70 : 55));
            continue;
        }
        if (age >= 60 || !visual(r) || std::ranges::any_of(world.at("kills"), [&](const Json &k) {
                return k.at("target") == r.at("id");
            }))
            continue;
        if (encounter(actor_point(r), 46, true) < 1e6)
            delay += (1 - age / 60.) * r.value("confidence", 1.) * 12;
    }
    if (observer.contains("crossingCalls"))
        for (auto &c : observer.at("crossingCalls"))
            screen(c.at("item"), c.at("point"), c.at("end"));
    return obstruction + std::min(delay, 36.);
}

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
// Review the route to the publicly announced site or to the captain's observed
// device. The server's C4 coordinates and the T plan are outside this decision.
void review_retake(Json &w, const Json &cfg, const OpeningMap &arena, const Squad &squad, const Json &captain,
                   const std::string &site) {
    auto &plan = w.at("plans").at("CT");
    const auto &nav = arena.objectives().map();
    const Tick now = w.at("tick"), left = w.at("deadline").get<Tick>() - now;
    Point goal = arena.site_point(site);
    bool located = active(captain, "seenDevice") && captain.at("seenDevice").at("site") == site;
    if (located)
        goal = actor_point(captain.at("seenDevice"));
    const auto prior = plan.value("retakeCall", Json::object());
    Json arrivals = Json::object();
    double slack = -1e6, earliest = 1e6, health = 0, investment = 0;
    int items = 0, inTime = 0;
    std::string defuser;
    Json walk = Json::object();
    const bool revised = revised_defense(w);
    const bool opponents = std::ranges::count_if(w.at("kills"), [&](const Json &k) {
                               return std::ranges::none_of(w.at("agents"), [&](const Json &a) {
                                   return a.at("team") == "CT" && a.at("id") == k.at("target");
                               });
                           }) < 5;
    for (auto p : squad) {
        const auto pos = actor_point(*p);
        const auto id = p->at("id").get<std::string>();
        const auto area = p->at("navArea").get<AreaId>();
        auto floor = located ? nav.use_position(area, pos, goal, 6) : std::optional<Point>{goal};
        double eta = 1e6;
        if (floor) {
            auto zone = nav.locate(*floor);
            if (zone)
                if (auto route = nav.path(area, pos, *zone, *floor, {})) {
                    const double speed = 2 * move_speed(player_profile(w, *p));
                    eta = std::ceil(walk_length(pos, *route) / speed);
                    if (revised) {
                        walk[id] = eta;
                        if (eta > 0 || !located) {
                            double clear = opponents ? std::min(9., eta / 9.) + 4 * !located : 0.;
                            double resistance = route_resistance(w, cfg, nav, captain, pos, *route, speed);
                            eta += std::ceil(clear + resistance);
                        }
                        // Reload, draw and throw recovery can overlap running.
                        eta = std::max(
                            eta, double(std::max(p->at("ready").get<Tick>(), p->at("reloadAt").get<Tick>()) -
                                        now));
                    }
                }
        }
        const int use = cfg.at("rules").at(p->at("kit") == true ? "kitDefuse" : "defuse");
        arrivals[id] = eta;
        inTime += eta + 6 < left;
        health += p->at("hp").get<int>() / 100.;
        investment += equipment_value(*p, cfg);
        items += int(p->at("utility").size());
        // Prefer to keep an existing assignment on a near tie.
        const double finish = eta + use;
        const double cost = finish - 3 * (finish < left && prior.value("defuser", std::string{}) == id);
        if (cost < earliest) {
            earliest = cost;
            slack = left - finish;
            defuser = id;
        }
    }
    std::set<std::string> dead;
    for (auto &k : w.at("kills"))
        dead.insert(k.at("target"));
    double opposition = 0;
    for (const auto &r : captain.at("knowledge")) {
        const auto age = now - r.at("tick").get<Tick>();
        if (age >= 0 && age < 65 && visual(r) && !dead.contains(r.at("id").get<std::string>()) &&
            !r.value("disputed", false) && distance(actor_point(r), goal) < 75)
            opposition += (1 - age / 65.) * r.value("confidence", 1.);
    }
    int deadT = 0;
    for (const auto &id : dead)
        deadT += std::ranges::none_of(
            w.at("agents"), [&](const Json &p) { return p.at("team") == "CT" && p.at("id") == id; });
    const int enemies = std::max(0, 5 - deadT);
    const auto &skills = player_profile(w, captain).at("skills");
    // A public living opponent is a risk, but a fresh position on the site
    // carries more weight than an opponent whose whereabouts are unknown.
    const auto &use = w.at("action");
    const bool defusing = !use.empty() && use.at("kind") == "defuse" &&
                          std::ranges::any_of(squad, [&](auto p) { return p->at("id") == use.at("player"); });
    if (defusing) {
        defuser = use.at("player");
        slack = w.at("deadline").get<Tick>() - use.at("end").get<Tick>();
    }
    double isolated = 0;
    if (revised && !defusing && opposition > 0 && !defuser.empty()) {
        double support = 1e6;
        for (const auto &[id, eta] : arrivals.items())
            if (id != defuser)
                support = std::min(support, eta.get<double>());
        isolated = std::clamp((support - arrivals.at(defuser).get<double>()) / 5., 0., 10.) *
                   std::min(1., opposition);
    }
    const double take = 27 + 6 * health + 2 * std::min(items, 6) + 3 * inTime +
                        .17 * skills.at("retakes").get<int>() + std::clamp(slack / 3., -30., 16.) -
                        7 * opposition - isolated - 3 * std::max(0, enemies - inTime);
    const double keep = 15 + std::min(22., investment / squad.size() / 220.) +
                        .12 * (100 - skills.at("risk").get<int>()) +
                        5 * (prior.value("kind", std::string{}) == "save");
    const bool save = slack <= 0 || (!defusing && keep > take);
    std::string kind = save ? "save" : "retake";
    const bool changed =
        prior.value("kind", std::string{}) != kind || prior.value("defuser", std::string{}) != defuser;
    const bool rebuild = !plan.contains("retake") || prior.value("alive", 0u) != squad.size() ||
                         prior.value("located", false) != located ||
                         prior.value("kind", std::string{}) == "save";
    if (save)
        plan.erase("retake");
    else if (rebuild || changed) {
        for (auto p : squad)
            if (prior.value("kind", std::string{}) == "save" || p->at("id") == defuser)
                p->erase("saving");
        assemble_retake(w, cfg, arena, squad, captain, site);
    }
    // One discretionary thrower per entry. A separate entrance can support
    // simultaneously. A player already committed to the device takes it first.
    Json throwers = Json::array();
    if (!save && plan.contains("retake")) {
        const auto &duties = plan.at("retake").at("duties");
        Squad candidates;
        for (auto p : squad)
            if (!p->at("utility").empty() && !active(*p, "saving") &&
                arrivals.at(p->at("id").get<std::string>()) < left)
                candidates.push_back(p);
        auto cost = [&](const Json *p) {
            auto id = p->at("id").get<std::string>();
            auto &s = player_profile(w, *p).at("skills");
            return arrivals.at(id).get<double>() + 50 * (id == defuser) - s.at("support").get<int>() / 6.;
        };
        std::stable_sort(candidates.begin(), candidates.end(),
                         [&](auto a, auto b) { return cost(a) < cost(b); });
        std::vector<Point> entries;
        for (auto p : candidates) {
            const std::string id = p->at("id");
            const Point entry =
                duties.contains(id) ? duties.at(id).at("entry").get<Point>() : actor_point(*p);
            if (std::ranges::none_of(entries, [&](const Point &q) { return distance(entry, q) < 24; })) {
                entries.push_back(entry);
                throwers.push_back(id);
            }
        }
    }
    plan["retakeCall"] = {{"throwers", throwers}, {"kind", kind},          {"defuser", defuser},
                          {"eta", arrivals},      {"slack", slack},        {"site", site},
                          {"located", located},   {"alive", squad.size()}, {"takeScore", take},
                          {"saveScore", keep}};
    if (revised) {
        auto &call = plan.at("retakeCall");
        call["walk"] = std::move(walk);
        if (!save) {
            Json sectors = Json::object();
            std::vector<Point> threats;
            for (const auto &r : captain.at("knowledge")) {
                const auto age = now - r.at("tick").get<Tick>();
                if (age >= 0 && age < 35 && visual(r) && !r.value("disputed", false) &&
                    !dead.contains(r.at("id").get<std::string>()) && distance(actor_point(r), goal) < 65)
                    threats.push_back(actor_point(r));
            }
            for (const auto &lane : arena.objectives().ingress().at(site)) {
                auto at =
                    std::find_if(lane.rbegin(), lane.rend(), [&](auto &q) { return distance(q, goal) > 12; });
                if (at != lane.rend())
                    threats.push_back(*at);
            }
            // Once the entries are covered, additional teammates clear separate
            // named hiding places on the way to the device.
            for (const auto &[area, point] : arena.layout().holds.at(site))
                if (distance(point, goal) > 8)
                    threats.push_back(point);
            Squad cover = squad;
            std::stable_sort(cover.begin(), cover.end(), [&](auto l, auto r) {
                return distance(actor_point(*l), goal) < distance(actor_point(*r), goal);
            });
            int assigned = 0;
            for (auto p : cover) {
                if (p->at("id") == defuser || threats.empty())
                    continue;
                Point q = threats.front();
                sectors[p->at("id").get<std::string>()] = {{"watch", q},
                                                           {"role", assigned++ == 0 ? "cover" : "clear"}};
                std::erase_if(threats, [&](auto other) { return distance(other, q) < 9; });
            }
            call["sectors"] = std::move(sectors);
        }
    }
    if (changed)
        emit(w, "defense_call", save ? "Сохранить оружие" : "Совместный ретейк " + site, "CT")
            .update({{"player", captain.at("id")},
                     {"decision", kind},
                     {"site", site},
                     {"defuser", defuser},
                     {"eta", arrivals},
                     {"slack", slack}});
}
} // namespace esport
