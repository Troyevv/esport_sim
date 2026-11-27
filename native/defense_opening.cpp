#include "opening.hpp"
#include <algorithm>
#include <cmath>

namespace esport {
namespace {
using Points = std::vector<Point>;
Point xyz(const Json &a) { return {a.at("x"), a.at("y"), a.at("z")}; }
Point point(const Waypoint &n) { return {std::get<0>(n), std::get<1>(n), std::get<2>(n)}; }
auto path(const PhysicalNavigation &nav, const Point &a, const Point &b) -> std::optional<WalkPath> {
    auto from = nav.locate(a), to = nav.locate(b);
    return from && to ? nav.path(*from, a, *to, b, {}) : std::nullopt;
}
bool line(const PhysicalNavigation &nav, const Point &a, const Point &b) { return !nav.hit(a, b, 1, 64, 64); }
Points nearby(const PhysicalNavigation &nav, const Point &origin, double radius) {
    Points result;
    for (auto &[id, p] : nav.centers())
        if (distance(origin, p) < radius)
            result.push_back(p);
    return result;
}
template <typename T, typename F> void ordered(T &v, F rank) {
    std::stable_sort(v.begin(), v.end(), [&](const auto &a, const auto &b) { return rank(a) < rank(b); });
}
void nearest(Points &v, const Point &q) {
    ordered(v, [&](const Point &p) { return distance(p, q); });
}
bool has(const Json &seq, const Json &v) { return std::find(seq.begin(), seq.end(), v) != seq.end(); }
using Players = std::vector<const Json *>;
Players defenders(const Json &w) {
    Players ps;
    for (auto &a : w.at("agents"))
        if (a.at("team") == "CT")
            ps.push_back(&a);
    return ps;
}
std::string id(const Json *p) { return p->at("id"); }
const Json &skills(const Json &w, const Json *p) {
    return w.at("domain").at("players").at(p->at("playerId").get<std::string>()).at("skills");
}
} // namespace

Json OpeningMap::positions(const std::string &zone, const Point &origin, bool cautious) const {
    const auto &nav = objectives_->map();
    auto &z = defense_.at("zones").at(zone);
    auto seats = stations_.at(z[1].get<std::string>());
    const auto &targets = stations_.at(z[2].get<std::string>());
    if (targets.empty())
        throw std::invalid_argument("Нет ориентиров сектора");
    nearest(seats, origin);
    for (auto &post : seats) {
        if (!path(nav, origin, post))
            continue;
        auto toward = *std::min_element(targets.begin(), targets.end(), [&](const auto &a, const auto &b) {
            return distance(post, a) < distance(post, b);
        });
        auto neighbors = nearby(nav, post, 38);
        Points views{toward};
        if (auto onward = path(nav, post, toward))
            for (auto n = onward->rbegin(); n != onward->rend(); ++n)
                if (distance(post, point(*n)) > 9)
                    views.push_back(point(*n));
        auto alternatives = nearby(nav, toward, 22);
        std::erase_if(alternatives, [&](const Point &p) { return std::abs(p[2] - toward[2]) >= 10; });
        ordered(alternatives, [&](const Point &p) { return std::pair{distance(p, toward), p}; });
        views.insert(views.end(), alternatives.begin(),
                     alternatives.begin() + std::min<std::size_t>(10, alternatives.size()));
        for (auto &watch : views) {
            Points peeks{post};
            peeks.insert(peeks.end(), neighbors.begin(), neighbors.end());
            std::erase_if(peeks, [&](const Point &p) {
                auto d = distance(p, watch);
                return d <= 5 || d >= 115 || !line(nav, p, watch);
            });
            ordered(peeks, [&](const Point &p) {
                return distance(p, post) + (cautious ? 0. : .35 * distance(p, watch));
            });
            for (auto &peek : peeks) {
                auto route = path(nav, origin, peek);
                if (!route)
                    continue;
                Points cover;
                for (auto &n : *route)
                    cover.push_back(point(n));
                cover.insert(cover.end(), neighbors.begin(), neighbors.end());
                std::erase_if(cover, [&](const Point &p) {
                    auto d = distance(p, peek);
                    return d <= 9 || d >= 33 || !line(nav, p, peek);
                });
                ordered(cover, [&](const Point &p) {
                    return std::tuple{!line(nav, p, watch), std::abs(distance(p, peek) - 18),
                                      distance(p, origin)};
                });
                for (auto &back : cover)
                    if (path(nav, back, peek) && path(nav, peek, back))
                        return Json::array({back, peek, watch});
            }
        }
    }
    return nullptr;
}

std::string OpeningMap::draft(const Json &w, Json &captain, Json &plan, const Json &predicted,
                              const Json &explicit_site) const {
    const auto &nav = objectives_->map();
    auto choice = select_defense(w, captain, plan, predicted, explicit_site);
    std::string name = choice[0];
    auto zones = choice[1];
    bool quiet = choice[2];
    auto site_for = [&](const Json &zone) { return defense_.at("zones").at(zone.get<std::string>())[0]; };
    Json stack = explicit_site;
    if (stack.is_null() && quiet &&
        (plan.at("buy") == "Эко" || plan.at("buy") == "Форс" || plan.at("buy") == "Частичная"))
        stack = predicted;
    if (!stack.is_null()) {
        std::vector<std::string> wanted;
        for (auto it = defense_.at("zones").begin(); it != defense_.at("zones").end(); ++it)
            if (it.value()[0] == stack)
                wanted.push_back(it.key());
        for (int slot : std::array{4, stack == "A" ? 2 : 3, stack == "A" ? 3 : 2}) {
            if (std::count_if(zones.begin(), zones.end(),
                              [&](const Json &z) { return site_for(z) == stack; }) >= 4)
                break;
            if (site_for(zones.at(slot)) != stack) {
                auto rank = [&](const std::string &z) {
                    return std::pair{std::count(zones.begin(), zones.end(), z), z};
                };
                zones.at(slot) =
                    *std::min_element(wanted.begin(), wanted.end(),
                                      [&](const auto &a, const auto &b) { return rank(a) < rank(b); });
            }
        }
        name = "Усиление " + stack.get<std::string>() + " · " + name;
    }
    auto squad = defenders(w), sorted = squad;
    ordered(sorted, [](auto p) { return p->at("slot").template get<int>(); });
    auto &fallback = plan.at("orders").at("slots");
    Json jobs = Json::object();
    for (auto p : sorted) {
        int slot = p->at("slot");
        auto z = zones.at(slot);
        std::string site = site_for(z);
        auto &original = fallback.at(slot);
        if (original.at("site") != site) {
            auto &base = fallback.at(site == "A" ? 0 : 1);
            int lane = base.at("lane");
            Json relief;
            for (const auto &[q, watch] : angles(site, lane, sites_.at(site), "site")) {
                if (std::ranges::any_of(fallback, [&](const Json &a) {
                        return a.at("site") == site && distance(a.at("hold").template get<Point>(), q) < 5;
                    }))
                    continue;
                auto dest = nav.locate(q);
                if (dest && nav.path(p->at("navArea"), xyz(*p), *dest, q, {})) {
                    relief =
                        Json{{"id", id(p)}, {"site", site}, {"lane", lane}, {"hold", q}, {"watch", watch}};
                    break;
                }
            }
            if (relief.is_null())
                relief = Json{
                    {"hold", base.at("hold")}, {"watch", base.at("watch")}, {"lane", lane}, {"site", site}};
            original.update(relief);
        }
        original.erase("screen");
        Json job = {{"zone", z}, {"site", site}, {"role", "наблюдение"}, {"home", original.at("hold")}};
        auto coords = positions(z, xyz(*p), quiet);
        if (!coords.is_null()) {
            job["gate"] = coords[0];
            job["peek"] = coords[1];
            job["watch"] = coords[2];
        } else
            job["reason"] = "Нет достижимой пары позиций";
        jobs[id(p)] = std::move(job);
    }
    auto pair_up = [&](const Json *scout, const Json *support, bool handoff) {
        auto &first = jobs.at(id(scout));
        auto &second = jobs.at(id(support));
        Json copy = Json::object();
        for (auto k : {"gate", "peek", "watch", "zone"})
            if (handoff || k != std::string("zone"))
                copy[k] = first.at(k);
        if (handoff) {
            Json prior = Json::object();
            for (auto k : {"gate", "peek", "watch", "zone"})
                prior[k] = second.at(k);
            second["handoff"] = std::move(prior);
        }
        second.update(copy);
        first.update(Json{{"role", "разведка"}, {"partner", id(support)}});
        second.update(Json{{"role", "страховка"}, {"partner", id(scout)}});
    };
    std::set<std::string> seen;
    for (auto &z : zones)
        if (seen.insert(z.get<std::string>()).second) {
            Players members;
            for (auto p : squad)
                if (jobs.at(id(p)).at("zone") == z && jobs.at(id(p)).contains("gate"))
                    members.push_back(p);
            if (members.size() < 2)
                continue;
            ordered(members, [&](auto p) {
                const auto &s = skills(w, p);
                return -(s.at("map_control").template get<int>() + s.at("decisions").template get<int>() -
                         distance(xyz(*p), jobs.at(id(p)).at("gate").template get<Point>()) / 3);
            });
            if (path(nav, xyz(*members[1]), jobs.at(id(members[0])).at("gate").template get<Point>()))
                pair_up(members[0], members[1], false);
        }
    std::vector<std::pair<const Json *, const Json *>> pairs;
    for (auto scout : squad)
        for (auto escort : squad) {
            auto &a = jobs.at(id(scout));
            auto &b = jobs.at(id(escort));
            if (scout != escort && a.at("role") == "наблюдение" && b.at("role") == "наблюдение" &&
                a.contains("gate") && b.contains("gate") && a.at("site") == b.at("site"))
                pairs.emplace_back(scout, escort);
        }
    ordered(pairs, [&](const auto &pair) {
        auto [a, b] = pair;
        std::string i = a->at("playerId"), j = b->at("playerId");
        return distance(jobs.at(id(a)).at("gate").template get<Point>(),
                        jobs.at(id(b)).at("gate").template get<Point>()) -
               skills(w, b).at("support").template get<int>() / 5. -
               w.at("domain").at("chemistry").value(std::min(i, j) + "|" + std::max(i, j), 0) / 4.;
    });
    for (auto [a, b] : pairs) {
        Point first = jobs.at(id(a)).at("gate"), second = jobs.at(id(b)).at("gate");
        if (distance(first, second) <= 165 && path(nav, xyz(*b), first) && path(nav, first, second)) {
            pair_up(a, b, true);
            break;
        }
    }
    std::vector<std::string> focus;
    auto add = [&](const Json &z) {
        if (std::find(focus.begin(), focus.end(), z.get<std::string>()) == focus.end())
            focus.push_back(z);
    };
    for (auto &job : jobs)
        if (job.at("role") == "разведка")
            add(job.at("zone"));
    for (auto &z : zones)
        add(z);
    const auto target = explicit_site.is_null() ? predicted : explicit_site;
    if (!target.is_null())
        ordered(focus, [&](const auto &z) { return site_for(z) != target; });
    if (focus.size() > 2)
        focus.resize(2);
    plan["opening"] = Json{{"jobs", jobs},
                           {"quiet", quiet},
                           {"reports", Json::object()},
                           {"salvos", Json::object()},
                           {"focus", focus}};
    plan["formation"] = name;
    return name;
}

Json OpeningMap::lineup(const Point &origin, const Point &gate, const Point &peek, const Point &watch,
                        const std::string &item, double radius) const {
    const auto &nav = objectives_->map();
    auto route = path(nav, origin, gate);
    if (!route)
        return nullptr;
    auto neighbors = nearby(nav, gate, 28), sorted = neighbors;
    nearest(sorted, gate);
    Points launches{origin};
    for (auto &n : *route)
        launches.push_back(point(n));
    launches.push_back(gate);
    launches.insert(launches.end(), sorted.begin(),
                    sorted.begin() + std::min<std::size_t>(sorted.size(), 12));
    auto targets = nearby(nav, watch, radius - 2);
    ordered(targets, [&](const Point &q) { return std::pair{distance(q, watch), q}; });
    targets.insert(targets.begin(), watch);
    std::erase_if(targets, [&](const Point &q) {
        return std::abs(q[2] - watch[2]) >= 12 || !line(nav, q, watch) ||
               (distance(q, gate) <= radius + 2 && line(nav, gate, q)) ||
               (item != "Свет" && distance(q, peek) <= radius + 3);
    });
    std::set<Point> used;
    for (auto &launch : launches)
        if (used.insert(launch).second)
            for (auto &target : targets) {
                double d = distance(launch, target);
                if (d <= std::max(16., radius + 2) || d >= 105)
                    continue;
                auto trajectory = nav.grenade(launch, target, std::max(3, int(std::nearbyint(d / 7))));
                if (distance(trajectory.back(), target) >= 6)
                    continue;
                if (std::find(neighbors.begin(), neighbors.end(), launch) != neighbors.end() &&
                    (!path(nav, origin, launch) || !path(nav, launch, gate)))
                    continue;
                return Json::array({launch, target});
            }
    return nullptr;
}

void OpeningMap::equip_defense(const Json &w, Json &plan, const Json &cfg) const {
    auto &opening = plan.at("opening");
    auto &jobs = opening.at("jobs");
    auto squad = defenders(w);
    ordered(squad, [&](auto p) {
        return std::pair{jobs.at(id(p)).at("role") != "страховка", p->at("slot").template get<int>()};
    });
    for (auto p : squad) {
        auto &job = jobs.at(id(p));
        if (!job.contains("gate") || opening.at("quiet") == true || !has(opening.at("focus"), job.at("zone")))
            continue;
        bool support = job.at("role") == "страховка";
        std::vector<std::string> options = support ? std::vector<std::string>{"Свет", "Дым"}
                                                   : std::vector<std::string>{"Огонь", "Дым", "Свет"};
        bool carried = false;
        for (const auto &g : options)
            if (has(p->at("utility"), g)) {
                carried = true;
                auto key = job.at("zone").get<std::string>() + (g == "Свет" ? "/flash" : "/screen");
                if (opening.at("salvos").contains(key))
                    continue;
                auto coords = lineup(xyz(*p), job.at("gate"), job.at("peek"), job.at("watch"), g,
                                     cfg.at("utility").at(g)[0]);
                if (coords.is_null()) {
                    job["utilityReason"] = "Нет проверенной траектории";
                    continue;
                }
                job.erase("utilityReason");
                job["throw"] = Json{{"item", g},
                                    {"launch", coords[0]},
                                    {"target", coords[1]},
                                    {"forPlayer", job.value("partner", id(p))}};
                opening.at("salvos")[key] = id(p);
                break;
            }
        if (!carried)
            job["utilityReason"] = "Нет подходящей гранаты";
    }
}
} // namespace esport
