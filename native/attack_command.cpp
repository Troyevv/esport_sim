#include "team_ai.hpp"
#include <algorithm>
#include <limits>

namespace esport {
namespace {
// The same reverse NAV costs used by the opening planner, in simulation ticks.
double travel_ticks(const OpeningMap &arena, const std::string &site, AreaId area) {
    return arena.objectives().site_cost(site, area, std::numeric_limits<double>::infinity()) /
           (arena.objectives().map().unit() * 1.65);
}

// After taking space, do not send a player back through spawn-side markers.
// Keep the remaining ordered suffix, including the final entry to the site.
void resume_routes(const OpeningMap &arena, Json &plan, const Squad &squad) {
    const std::string site = plan.at("site");
    for (auto a : squad) {
        const auto &route = plan.at("orders").at("slots").at(a->at("slot").get<int>()).at("via");
        const auto cost = travel_ticks(arena, site, a->at("navArea"));
        size_t index = 0;
        while (index < route.size()) {
            auto area = arena.objectives().map().locate(route.at(index));
            if (!area || travel_ticks(arena, site, *area) <= cost + 4)
                break;
            ++index;
        }
        (*a)["waypoint"] = index;
    }
}
} // namespace

void review_attack(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                   const Json &captain, const Reports &reports) {
    const Tick now = w.at("tick"), remaining = w.at("deadline").get<Tick>() - now;
    const auto &skills = player_profile(w, captain).at("skills");
    plan["review"] = now + 8 + (200 - skills.at("calling").get<int>() - skills.at("adaptability").get<int>()) / 8;
    const std::string site = plan.at("site"), other = site == "A" ? "B" : "A";
    // A dropped C4 follows the existing recovery assignment.
    const Json *carrier = nullptr;
    for (auto a : squad)
        if (a->at("id") == w.at("bomb").at("carrier"))
            carrier = a;
    if (!carrier || !w.at("action").empty())
        return;

    const int plant = cfg.at("rules").at("plant");
    const auto area = carrier->at("navArea").get<AreaId>();
    const double travel = travel_ticks(arena, site, area);
    const bool urgent = remaining <= travel + plant + 45;
    Reports credible;
    for (auto r : reports)
        if (!r->value("disputed", false) || r->value("confidence", 0.) >= .5)
            credible.push_back(r);
    auto pressure = site_pressure(arena, credible, now);
    sector_pressure(arena, credible, {}, now, pressure);
    std::map<std::string, int> held, blocked;
    const auto &stations = plan.find("probe");
    const bool probing = stations != plan.end() && stations->contains("stations") && !stations->contains("released");
    for (auto a : squad) {
        const std::string id = a->at("id");
        const auto &calls = a == &captain ? captain.find("sentFeedback") : captain.find("peerCalls");
        if (calls == captain.end())
            continue;
        auto feedback = calls->find(a == &captain ? "sector" : id + "/sector");
        if (feedback == calls->end() || now - feedback->at("tick").get<Tick>() >= 32)
            continue;
        const std::string sector = feedback->at("order");
        if (feedback->at("state") == "held")
            ++held[sector];
        else
            ++blocked[sector];
    }
    for (const auto &row : captain.at("routeReports"))
        if (now - row[1].get<Tick>() < 45)
            ++blocked[row[0].get<std::string>()];

    const bool obstructed = blocked[site] > 0 && blocked[other] == 0;
    const bool contested = pressure[site] >= (squad.size() < 4 ? 1.25 : 1.65) &&
                           pressure[site] - pressure[other] > (held[other] ? .55 : 1.);
    const bool rotate = !plan.at("rotated").get<bool>() && !urgent &&
                        (obstructed || contested) && remaining > travel_ticks(arena, other, area) + plant + 65;
    // Release on a local report, casualties or a bounded information budget.
    // Leave enough round clock for the carrier to reach the selected objective.
    const Tick elapsed = now - plan.at("start").get<Tick>();
    const bool regroup = !rotate && !urgent && squad.size() >= 2 && squad.size() <= 3 &&
                         !plan.contains("regroup") && travel > 20 &&
                         std::ranges::any_of(squad, [&](auto a) {
                             return distance(actor_point(*a), actor_point(*carrier)) > 35;
                         });
    bool release = probing && (rotate || held[site] + held[other] >= int(squad.size()) - 1 ||
                               blocked[site] || blocked[other] || squad.size() < 4 || urgent ||
                               elapsed >= 90 + skills.at("patience").get<int>());
    if (!release && !rotate && !regroup)
        return;
    if (release)
        plan.at("probe")["released"] = now;
    if (regroup) {
        plan["style"] = "Групповой выход";
        plan["orders"] = arena.attack_orders(w, site, plan.at("lane"), plan.at("style"));
        plan["regroup"] = {{"point", actor_point(*carrier)}, {"until", now + 28}};
    }
    if (rotate) {
        if (plan.contains("regroup"))
            plan.at("regroup")["until"] = now;
        const int lane = 1 - plan.at("lane").get<int>();
        plan["orders"] = arena.attack_orders(w, other, lane, plan.at("style"));
        plan["lane"] = lane;
        plan["site"] = other;
        plan["rotated"] = true;
    }
    resume_routes(arena, plan, squad);
    const std::string reason = rotate ? (obstructed ? "перекрыт подход" : "сопротивление на направлении")
                               : urgent ? "таймер установки" : squad.size() < 4 ? "потеря игроков"
                               : held[site] + held[other] >= int(squad.size()) - 1 ? "сектора заняты"
                               : blocked[site] || blocked[other] ? "потеря контроля" : "истекло время разведки";
    emit(w, rotate ? "rotate" : regroup ? "regroup" : "execute", captain.at("name").get<std::string>() + " · " + reason +
         " · выход на " + plan.at("site").get<std::string>(), "T")
        .update(Json{{"player", captain.at("id")}, {"site", plan.at("site")}, {"from", site}, {"reason", reason},
                     {"pressure", pressure}, {"held", held}, {"blocked", blocked}});
}
} // namespace esport
