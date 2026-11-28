#include "defense_command.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace esport {
namespace {
std::string id(const Json *p) { return p->at("id"); }
int slot(const Json *p) { return p->at("slot"); }
Json station(const OpeningMap &arena, const Json &actor, const std::string &site, int lane,
             const OpeningMap::Angles &choices, const std::vector<Point> &occupied, double radius) {
    auto &nav = arena.objectives().map();
    for (auto &[goal, watch] : choices) {
        if (std::ranges::any_of(occupied, [&](auto &p) { return distance(goal, p) < radius; }))
            continue;
        auto to = nav.locate(goal);
        if (to && nav.path(actor.at("navArea"), actor_point(actor), *to, goal, {}))
            return Json{
                {"id", actor.at("id")}, {"site", site}, {"lane", lane}, {"hold", goal}, {"watch", watch}};
    }
    return nullptr;
}
void assign(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &target, double pressure,
            bool second, int limit) {
    const auto key = second ? "secondBackup" : "backup";
    auto erase = [&]() { plan.erase(key); };
    if (target.is_null() || (second && ((limit < 0 && pressure < 2.5) || !plan.contains("backup") ||
                                        plan.at("backup").empty()))) {
        erase();
        return;
    }
    const auto site = target.get<std::string>();
    const auto &slots = plan.at("orders").at("slots");
    auto off = [&](Json *p) { return slots.at(slot(p)).at("site") != site; };
    auto unavailable = [&](Json *p) {
        return plan.at("unavailable").value(id(p), std::string{}) == site ||
               (plan.contains("retainedAnchor") && plan.at("retainedAnchor") == id(p));
    };
    Squad candidates;
    int lane;
    std::vector<Point> occupied;
    for (auto p : squad)
        if (slot(p) != 4 && !off(p))
            occupied.push_back(slots.at(slot(p)).at("hold").get<Point>());
    if (second) {
        const auto &first = plan.at("backup");
        auto away = std::count_if(squad.begin(), squad.end(), [&](auto p) { return slot(p) != 4 && off(p); });
        if (away < 2) {
            erase();
            return;
        }
        for (auto p : squad)
            if (!unavailable(p) && first.at("id") != id(p) &&
                (slot(p) == 4 || (off(p) && (slot(p) >= 2 || plan.contains("retainedAnchor")))))
                candidates.push_back(p);
        occupied.push_back(first.at("hold").get<Point>());
        lane = 1 - first.value("lane", plan.at("lane").get<int>());
    } else {
        for (auto p : squad)
            if ((off(p) || slot(p) == 4) && !unavailable(p) &&
                (pressure >= 1.65 || slot(p) == 4 ||
                 (limit > 0 && plan.at("defenseCall").at("kind") == "reclaim")))
                candidates.push_back(p);
        if (std::ranges::any_of(candidates, [](auto p) { return slot(p) >= 2; }))
            std::erase_if(candidates, [](auto p) { return slot(p) < 2; });
        else if (limit < 0 && candidates.size() == 1 &&
                 std::ranges::any_of(squad, [&](auto p) { return !off(p); })) {
            erase();
            return;
        }
        lane = plan.value("reliefLanes", Json::object()).value(site, plan.at("lane").get<int>());
    }
    if (limit > 0 && plan.at("defenseCall").at("kind") != "full") {
        // Always leave somebody responsible for the other site. Opening stacks
        // can give the nominal reserve a regular sector there as well.
        std::erase_if(candidates, [&](auto p) {
            return off(p) && std::ranges::none_of(squad, [&](auto mate) {
                       return mate != p && off(mate) && (!second || plan.at("backup").at("id") != id(mate));
                   });
        });
    }
    if (candidates.empty()) {
        erase();
        return;
    }
    if (plan.contains(key) && !plan.at(key).empty() && plan.at(key).at("site") == site &&
        std::ranges::any_of(candidates, [&](auto p) { return plan.at(key).at("id") == id(p); }))
        return;
    const auto center = arena.site_point(site);
    auto rank = [&](Json *p) {
        return std::tuple{
            arena.objectives().site_cost(site, p->at("navArea"), std::numeric_limits<double>::infinity()),
            second ? 0. : distance(actor_point(*p), center), slot(p)};
    };
    std::stable_sort(candidates.begin(), candidates.end(), [&](auto l, auto r) { return rank(l) < rank(r); });
    auto choices = arena.angles(site, lane, center, "site");
    for (auto p : candidates) {
        auto duty = station(arena, *p, site, lane, choices, occupied, 6);
        if (!duty.empty()) {
            plan[key] = std::move(duty);
            return;
        }
    }
    erase();
}
} // namespace
void assign_reserves(const OpeningMap &arena, Json &plan, const Squad &squad, Json destination,
                     const Pressure &counts, Tick now, const Json &bomb_site, int limit) {
    auto order = [&](const std::string &key) { return plan.value(key, Json(nullptr)); };
    auto en_route = [&](const Json &o, const Json &other) {
        if (o.empty() || now > o.value("arriveBy", Tick{-1}))
            return false;
        auto actor =
            std::find_if(squad.begin(), squad.end(), [&](auto p) { return p->at("id") == o.at("id"); });
        if (actor == squad.end() ||
            (plan.contains("retainedAnchor") && plan.at("retainedAnchor") == o.at("id")) ||
            o.at("site") == plan.at("unavailable").value(id(*actor), std::string{}) ||
            distance(actor_point(**actor), o.at("hold").get<Point>()) < 8)
            return false;
        std::string site = o.at("site"), away = site == "A" ? "B" : "A";
        if (counts.at(away) >= .65 && counts.at(away) > counts.at(site))
            return false;
        return std::ranges::any_of(squad, [&](auto p) {
            return p != *actor && (other.empty() || p->at("id") != other.at("id")) && slot(p) != 4 &&
                   plan.at("orders").at("slots").at(slot(p)).at("site") == away;
        });
    };
    auto first = order("backup"), second = order("secondBackup");
    auto value = [&]() { return destination.is_null() ? 0. : counts.at(destination.get<std::string>()); };
    if (en_route(first, second))
        destination = first.at("site");
    else
        assign(arena, plan, squad, destination, value(), false, limit);
    first = order("backup");
    if (limit == 1)
        plan.erase("secondBackup");
    else if (first.empty() || second.empty() || !second.value("objectiveConfirmed", false) ||
             second.at("id") == first.at("id") || second.at("site") != destination ||
             !en_route(second, first))
        assign(arena, plan, squad, destination, value(), true, limit);
    auto &nav = arena.objectives().map();
    for (auto k : {"backup", "secondBackup"})
        if (plan.contains(k) && !plan.at(k).empty()) {
            auto &duty = plan.at(k);
            if (bomb_site == duty.at("site"))
                duty["objectiveConfirmed"] = true;
            if (duty.contains("arriveBy") ||
                counts.at(duty.at("site").get<std::string>()) < (std::string(k) == "backup" ? 1.65 : 2.5))
                continue;
            auto p = std::find_if(squad.begin(), squad.end(), [&](auto a) { return duty.at("id") == id(a); });
            if (p == squad.end())
                throw std::invalid_argument("Отсутствует игрок с заданием");
            auto pos = actor_point(**p), goal = duty.at("hold").get<Point>();
            auto to = nav.locate(goal);
            if (to)
                if (auto path = nav.path((*p)->at("navArea"), pos, *to, goal, {})) {
                    double length = 0;
                    for (auto &[x, y, z, area] : *path) {
                        Point q{x, y, z};
                        length += distance(pos, q);
                        pos = q;
                    }
                    duty["arriveBy"] = plan.at("review").get<Tick>() + Tick(std::nearbyint(length / 1.65));
                }
        }
}
void commit_reserves(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &target) {
    Json prior = plan.value("commitments", Json::object());
    plan.erase("commitments");
    if (target.is_null())
        return;
    const auto site = target.get<std::string>();
    auto &slots = plan.at("orders").at("slots");
    std::vector<Point> occupied;
    for (auto p : squad) {
        auto &job = assignment(plan, *p, squad);
        if (job.at("site") == site && (slot(p) != 4 || relief(plan, *p)))
            occupied.push_back(job.at("hold").get<Point>());
    }
    Json duties = Json::object();
    for (auto p : squad) {
        if (plan.at("unavailable").value(id(p), std::string{}) == site || relief(plan, *p) ||
            (slot(p) != 4 && slots.at(slot(p)).at("site") == site))
            continue;
        auto duty = prior.value(id(p), Json(nullptr));
        if (duty.empty() || duty.at("site") != site || std::ranges::any_of(occupied, [&](auto &q) {
                return distance(duty.at("hold").get<Point>(), q) < 5;
            })) {
            int lane = slots.at(slot(p)).at("lane");
            duty = station(arena, *p, site, lane, arena.angles(site, lane, arena.site_point(site), "site"),
                           occupied, 5);
        }
        if (!duty.empty()) {
            duties[id(p)] = duty;
            occupied.push_back(duty.at("hold").get<Point>());
        }
    }
    plan["commitments"] = std::move(duties);
}
} // namespace esport
