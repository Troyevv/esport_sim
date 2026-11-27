#include "opening.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace esport {
namespace {
bool facing(const Point &from, const Point &watch, const Point &q) {
    const double dx = watch[0] - from[0], dy = watch[1] - from[1], x = q[0] - from[0], y = q[1] - from[1];
    return dx * x + dy * y >= .5 * std::hypot(dx, dy) * std::hypot(x, y);
}
bool sees(const PhysicalNavigation &nav, const Point &a, const Point &b) {
    return !nav.hit(a, b, 1, 64, 64, true);
}
bool reachable(const PhysicalNavigation &nav, const Point &a, const Point &b) {
    auto from = nav.locate(a), to = nav.locate(b);
    return from && to && nav.path(*from, a, *to, b, {});
}
bool contains(const std::vector<Point> &points, const Point &q) {
    return std::find(points.begin(), points.end(), q) != points.end();
}
} // namespace

Point OpeningMap::watch(const std::string &site, int lane, const Point &from) const {
    const auto &nav = objectives_->map();
    const auto &views = orders_.places.at(profile_.at(site).at(lane).back().get<std::string>());
    auto it = std::min_element(views.begin(), views.end(), [&](auto a, auto b) {
        return distance(nav.center(a), from) < distance(nav.center(b), from);
    });
    if (it == views.end())
        throw std::invalid_argument("Пустой сектор наблюдения");
    return nav.center(*it);
}

OpeningMap::Angles OpeningMap::angles(const std::string &site, int lane, const Point &anchor,
                                      const std::string &duty) const {
    const auto &nav = objectives_->map();
    auto ingress = objectives_->ingress().at(site).at(lane);
    if (duty == "junction")
        ingress = stations_.at(profile_.at("overwatch")[1].get<std::string>());
    std::vector<Point> plants;
    if (duty == "site") {
        plants = objectives_->samples(site);
        auto entries = ingress;
        std::erase_if(entries, [&](const Point &p) { return objectives_->site_at(p) == site; });
        if (!entries.empty())
            ingress = std::move(entries);
    }
    const auto plant = sites_.at(site);
    std::set<Point> covers, positions{anchor};
    for (const auto &p : orders_.cover)
        if (distance(p, anchor) <= 20 || (!plants.empty() && distance(p, plant) <= 27))
            covers.insert(p);
    positions.insert(covers.begin(), covers.end());
    for (const auto &[id, p] : nav.centers())
        if (distance(p, anchor) < 15 || (!plants.empty() && distance(p, plant) < 26))
            positions.insert(p);
    using Rank = std::tuple<bool, bool, bool, double, int, int, bool, double, Point, Point>;
    std::vector<Rank> ranked;
    for (const auto &pos : positions) {
        auto visible = [&](const std::vector<Point> &points) {
            std::vector<Point> out;
            for (const auto &q : points) {
                double d = distance(q, pos);
                if (d >= 5 && d <= 100 && sees(nav, pos, q))
                    out.push_back(q);
            }
            return out;
        };
        auto views = visible(plants), entries = visible(ingress);
        Point look;
        int joint = 0, n = entries.size();
        if (!views.empty() && !entries.empty()) {
            std::tuple<double, int, int, double> best{-1., 0, 0, 0.};
            auto consider = [&](const Point &q) {
                auto count = [&](const std::vector<Point> &v) {
                    return int(
                        std::count_if(v.begin(), v.end(), [&](const Point &p) { return facing(pos, q, p); }));
                };
                int j = count(views), e = count(entries);
                auto key = std::tuple{std::min(double(j) / plants.size(), double(e) / ingress.size()), j, e,
                                      -distance(q, plant)};
                if (key > best) {
                    best = key;
                    look = q;
                    joint = j;
                    n = e;
                }
            };
            for (auto &q : views)
                consider(q);
            for (auto &q : entries)
                consider(q);
        } else
            look = !entries.empty() ? entries.front()
                   : !views.empty() ? views.front()
                                    : watch(site, lane, pos);
        ranked.emplace_back(!plants.empty() && views.empty(), !n,
                            std::abs(pos[2] - anchor[2]) * nav.unit() > 72,
                            plants.empty() ? 0.
                                           : -std::min(double(joint) / plants.size(),
                                                       double(n) / std::max<std::size_t>(1, ingress.size())),
                            -joint, -std::min(6, n), !covers.contains(pos), distance(pos, anchor), pos, look);
    }
    std::sort(ranked.begin(), ranked.end());
    Angles result;
    for (const auto &row : ranked)
        result.emplace_back(std::get<8>(row), std::get<9>(row));
    return result;
}

OpeningMap::Angles OpeningMap::crossfire(const std::string &site, int lane, const Point &wing,
                                         const Point &anchor, const Point &anchor_watch) const {
    const auto &nav = objectives_->map();
    auto base = angles(site, lane, wing, "approach");
    auto entries = objectives_->ingress().at(site).at(lane), targets = entries;
    for (auto &q : objectives_->ingress().at(site).at(1 - lane))
        if (!contains(targets, q))
            targets.push_back(q);
    if (targets.empty())
        return base;
    auto plant = sites_.at(site);
    std::set<Point> candidates;
    for (auto &[id, p] : nav.centers())
        if (double d = distance(p, anchor); d > 8 && d < 45)
            candidates.insert(p);
    for (std::size_t i = 0; i < std::min<std::size_t>(base.size(), 24); ++i)
        candidates.insert(base[i].first);
    for (auto &[id, p] : orders_.holds.at(site))
        candidates.insert(p);
    auto visible = [&](const Point &p) {
        std::vector<Point> seen;
        for (auto &q : targets) {
            double d = distance(p, q);
            if (d > 5 && d < 95 && sees(nav, p, q))
                seen.push_back(q);
        }
        return seen;
    };
    auto anchor_views = visible(anchor);
    using Rank = std::tuple<bool, int, bool, double, double, double, Point, Point>;
    std::vector<Rank> ranked;
    for (auto &p : candidates) {
        double gap = distance(p, anchor);
        if (gap <= 7 || gap >= 52)
            continue;
        auto seen = visible(p);
        for (auto &q : seen) {
            if (!contains(anchor_views, q) || !facing(anchor, anchor_watch, q))
                continue;
            auto product = [&](unsigned j) { return (p[j] - q[j]) * (anchor[j] - q[j]); };
            auto cosine = sum3(product(0), product(1), product(2)) / (distance(p, q) * distance(anchor, q));
            if (cosine >= .78)
                continue;
            int extra = 0;
            for (auto &r : seen)
                extra += contains(entries, r) && facing(p, q, r) &&
                         (!contains(anchor_views, r) || !facing(anchor, anchor_watch, r));
            ranked.emplace_back(!contains(entries, q), -std::min(4, extra),
                                std::abs(p[2] - wing[2]) * 12 > 72, -std::min(distance(plant, q), 50.),
                                distance(p, wing), cosine, p, q);
        }
    }
    std::sort(ranked.begin(), ranked.end());
    Angles out;
    std::set<Point> used;
    for (auto &row : ranked)
        if (used.insert(std::get<6>(row)).second)
            out.emplace_back(std::get<6>(row), std::get<7>(row));
    for (auto &pair : base)
        if (used.insert(pair.first).second)
            out.push_back(pair);
    return out;
}

Json OpeningMap::screen(const std::string &site, int lane, const Point &origin, const Point &hold,
                        const Point &watch, const Point &anchor, const Point &partner_watch) const {
    const auto &nav = objectives_->map();
    auto from = nav.locate(origin), to = nav.locate(hold);
    if (!from || !to)
        return nullptr;
    auto path = nav.path(*from, origin, *to, hold, {});
    if (!path)
        return nullptr;
    const auto &entries = objectives_->ingress().at(site).at(lane);
    std::map<Point, double> options;
    double walked = 0;
    auto prev = origin;
    for (const auto &[x, y, z, area] : *path) {
        Point p{x, y, z};
        walked += distance(prev, p);
        prev = p;
        auto gap = distance(p, hold), a = distance(p, anchor);
        if (6 < gap && gap < 42 && 8 < a && a < 65)
            options[p] = walked;
    }
    for (const auto &q : entries) {
        if (sees(nav, hold, q) && facing(hold, watch, q))
            break;
        std::optional<std::pair<double, Point>> best;
        for (const auto &[p, length] : options)
            if (distance(p, q) > 6 && facing(anchor, partner_watch, p) && sees(nav, p, q) &&
                sees(nav, anchor, p)) {
                auto key = std::pair{length, p};
                if (!best || key < *best)
                    best = key;
            }
        if (best)
            return Json{{"site", site}, {"lane", lane}, {"hold", best->second}, {"watch", q}};
    }
    return nullptr;
}

Json OpeningMap::defense_orders(const Json &w, const std::string &site, int lane) const {
    const auto &nav = objectives_->map();
    Json slots = Json::array();
    std::vector<const Json *> squad;
    for (const auto &actor : w.at("agents"))
        if (actor.at("team") == "CT")
            squad.push_back(&actor);
    std::stable_sort(squad.begin(), squad.end(),
                     [](auto a, auto b) { return a->at("slot") < b->at("slot"); });
    for (const auto *a : squad) {
        int i = a->at("slot"), variant = (lane + i / 2) % 2;
        auto defended = i == 4 ? site : (i % 2 == 0 ? "A" : "B");
        auto plant = sites_.at(defended);
        auto &guards = profile_.at("guards").at(defended);
        std::string guard = i == 4 && profile_.contains("overwatch") ? profile_.at("overwatch")[0]
                                                                     : guards[(i / 2) % guards.size()];
        Point origin{a->at("x"), a->at("y"), a->at("z")};
        std::optional<Point> selected;
        auto ids = orders_.places.at(guard);
        std::sort(ids.begin(), ids.end());
        for (auto id : ids)
            if (nav.graph().route(a->at("navArea"), id, {}, {}) &&
                (!selected || distance(origin, nav.center(id)) < distance(origin, *selected)))
                selected = nav.center(id);
        auto hold = selected.value_or(plant);
        Angles views;
        std::vector<Point> via;
        if (selected) {
            if (i == 2 || i == 3)
                views = crossfire(defended, variant, hold, slots.at(i - 2).at("hold").get<Point>(),
                                  slots.at(i - 2).at("watch").get<Point>());
            else
                views = angles(defended, variant, hold,
                               i < 2                            ? "site"
                               : profile_.contains("overwatch") ? "junction"
                                                                : "approach");
            auto occupied = [&](const Point &p) {
                return std::ranges::any_of(slots, [&](const Json &row) {
                    return row.at("site") == defended && distance(p, row.at("hold").get<Point>()) < 6;
                });
            };
            auto sorted = views;
            std::stable_sort(sorted.begin(), sorted.end(), [&](const auto &a, const auto &b) {
                return occupied(a.first) < occupied(b.first);
            });
            for (const auto &[p, look] : sorted)
                if (reachable(nav, origin, p)) {
                    hold = p;
                    break;
                }
            if (reachable(nav, origin, hold))
                via.push_back(hold);
            else {
                std::vector<Point> nearby;
                for (auto &[id, p] : nav.centers())
                    if (p != hold && distance(p, hold) < 12)
                        nearby.push_back(p);
                std::stable_sort(nearby.begin(), nearby.end(), [&](const Point &a, const Point &b) {
                    return distance(a, hold) < distance(b, hold);
                });
                for (auto &p : nearby)
                    if (reachable(nav, origin, p)) {
                        via.push_back(p);
                        break;
                    }
            }
        }
        auto pos = via.empty() ? origin : via.back();
        std::vector<Point> options{hold};
        for (auto &[id, p] : orders_.holds.at(defended))
            options.push_back(p);
        options.push_back(plant);
        hold = pos;
        for (auto &p : options)
            if (reachable(nav, pos, p)) {
                hold = p;
                break;
            }
        auto view =
            std::find_if(views.begin(), views.end(), [&](const auto &pair) { return pair.first == hold; });
        auto look = view == views.end() ? watch(defended, variant, hold) : view->second;
        slots.push_back(Json{{"role", orders_.roles.at(i)},
                             {"approach", via.empty() ? hold : via.front()},
                             {"via", via},
                             {"stage", via.empty() ? plant : via.back()},
                             {"hold", hold},
                             {"plant", plant},
                             {"site", defended},
                             {"lane", variant},
                             {"watch", look}});
        if (i == 2 || i == 3) {
            auto s = screen(defended, variant, origin, hold, look, slots.at(i - 2).at("hold").get<Point>(),
                            slots.at(i - 2).at("watch").get<Point>());
            if (!s.is_null())
                slots.back()["screen"] = s;
        }
    }
    return Json{{"version", 1}, {"map", w.at("mapId")}, {"geometry", w.at("map_version")}, {"slots", slots}};
}
} // namespace esport
