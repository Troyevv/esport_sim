#include "team_ai.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace esport {
Point actor_point(const Json &a) { return {a.at("x"), a.at("y"), a.value("z", 0.)}; }
int chemistry(const Json &w, const Json &a, const Json &b) {
    std::string l = a.at("playerId"), r = b.at("playerId");
    return w.at("domain").at("chemistry").value(std::min(l, r) + "|" + std::max(l, r), 0);
}
const Json &player_profile(const Json &w, const Json &a) {
    return w.at("domain").at("players").at(a.at("playerId").get<std::string>());
}
const Json *relief(const Json &plan, const Json &a) {
    for (auto k : {"backup", "secondBackup"})
        if (plan.contains(k) && !plan.at(k).empty() && plan.at(k).at("id") == a.at("id"))
            return &plan.at(k);
    auto id = a.at("id").get<std::string>();
    if (plan.contains("commitments") && plan.at("commitments").contains(id))
        return &plan.at("commitments").at(id);
    return nullptr;
}
const Json &assignment(const Json &plan, const Json &a, const Squad &squad) {
    if (auto duty = relief(plan, a))
        return *duty;
    int i = a.at("slot");
    const auto &slots = plan.at("orders").at("slots"), &order = slots.at(i);
    if ((i == 2 || i == 3) && slots.at(i - 2).at("site") == order.at("site") &&
        std::ranges::none_of(squad, [&](auto p) {
            if (p->at("slot") != i - 2)
                return false;
            auto moved = relief(plan, *p);
            return !plan.contains("defenseCall") || !moved || moved->at("site") == order.at("site");
        }))
        return slots.at(i - 2);
    if (order.contains("screen") && !order.at("screen").empty() && !a.value("leftScreen", false))
        return order.at("screen");
    return order;
}
namespace {
std::optional<std::string> site_for(const OpeningMap &arena, const Point &p, bool &approach) {
    if (auto site = arena.objectives().reported_site(p)) {
        approach = false;
        return site;
    }
    approach = true;
    auto area = arena.objectives().map().locate(p);
    if (!area)
        return {};
    std::optional<std::string> result;
    for (const std::string site : {"A", "B"}) {
        bool found = false;
        for (const auto &lane : arena.profile().at(site))
            for (auto it = lane.end() - std::min<std::size_t>(2, lane.size()); it != lane.end(); ++it) {
                const auto &ids = arena.layout().places.at(it->get<std::string>());
                if (std::find(ids.begin(), ids.end(), *area) != ids.end())
                    found = true;
            }
        if (found) {
            if (result)
                return {};
            result = site;
        }
    }
    return result;
}
bool confirmed(const Json &r) { return r.at("source") == "Зрение" || r.at("source") == "Радио"; }
} // namespace
Pressure site_pressure(const OpeningMap &arena, const Reports &reports, Tick now) {
    Pressure counts{{"A", 0}, {"B", 0}}, groups = counts;
    Reports seen;
    for (auto r : reports)
        if (r->at("source") != "Слух") {
            auto prior = std::find_if(seen.begin(), seen.end(),
                                      [&](auto old) { return old->at("id") == r->at("id"); });
            if (prior == seen.end())
                seen.push_back(r);
            else if ((*prior)->at("tick") < r->at("tick"))
                *prior = r;
        }
    for (auto r : seen) {
        auto age = now - r->at("tick").get<Tick>();
        if (age < 0 || age >= 75)
            continue;
        auto p = actor_point(*r);
        bool approach;
        auto site = site_for(arena, p, approach);
        if (!site)
            continue;
        double weight = (1 - age / 75.) * (r->at("source") == "Граната" ? .45 : 1.);
        if (approach)
            weight *= .7;
        if (r->value("carryingC4", false))
            weight *= 2;
        if (r->contains("direction") && !r->at("direction").empty() && age <= 20) {
            const auto &q = arena.site_point(*site);
            double d = distance(p, q);
            if (d > 3) {
                auto v = r->at("direction").get<Point>();
                weight *=
                    1 + .25 * (sum3(v[0] * (q[0] - p[0]), v[1] * (q[1] - p[1]), v[2] * (q[2] - p[2])) / d);
            }
        }
        counts[*site] += weight;
        groups[*site] =
            std::max(groups[*site], r->value("groupSize", 0) * (1 - age / 75.) * (approach ? .7 : 1.));
    }
    for (auto &[site, v] : counts)
        v = std::max(v, groups.at(site));
    return counts;
}
void sector_pressure(const OpeningMap &arena, const Reports &reports, const Reports &calls, Tick now,
                     Pressure &counts) {
    std::map<std::string, std::map<std::string, double>> audio;
    for (auto r : reports) {
        auto age = now - r->at("tick").get<Tick>();
        if (!r->contains("sound") || r->at("sound").empty() || age < 0 || age >= 32)
            continue;
        bool approach;
        if (auto site = site_for(arena, actor_point(*r), approach)) {
            auto &value = audio[*site][r->at("sound").get<std::string>()];
            double strength = r->at("confidence").get<double>() * (1 - age / 32.);
            value = std::max(value, (r->value("repeated", false) && r->at("sound") == "Шаги" ? .84 : .54) *
                                        strength);
        }
    }
    for (auto &[site, value] : counts) {
        double sum = 0;
        for (auto &[sound, weight] : audio[site])
            sum += weight;
        value += std::min(.94, sum);
        Reports recent;
        for (auto c : calls)
            if (c->at("site") == site && now >= c->at("tick").get<Tick>() &&
                now - c->at("tick").get<Tick>() < 35)
                recent.push_back(c);
        if (std::ranges::any_of(
                recent,
                [](auto c) { return c->at("state") == "engaged" || c->at("state") == "unsupported"; }) &&
            std::ranges::any_of(reports, [&](const Json *r) {
                bool approach;
                return confirmed(*r) && now - r->at("tick").get<Tick>() < 25 &&
                       site_for(arena, actor_point(*r), approach) == site;
            }))
            value += .68;
        for (auto c : recent)
            if (c->at("state") == "watching") {
                const auto q = c->at("point").get<Point>();
                if (std::ranges::any_of(reports, [&](auto r) {
                        return confirmed(*r) && r->at("tick") >= c->at("tick") &&
                               distance(actor_point(*r), q) < 30;
                    }))
                    continue;
                if (std::ranges::any_of(reports, [&](auto r) {
                        return r->at("tick") < c->at("tick") && distance(actor_point(*r), q) < 25;
                    })) {
                    value = std::max(0., value - .45);
                    break;
                }
            }
    }
}
void captain_review(Json &w, const Json &cfg, const OpeningMap &arena, const std::string &side) {
    Squad squad;
    for (auto &a : w.at("agents"))
        if (a.at("team") == side && a.at("hp") != 0)
            squad.push_back(&a);
    if (squad.empty())
        return;
    auto priority = [](const Json *a) {
        return std::pair{a->at("appointed") == false, a->at("slot").get<int>()};
    };
    auto &captain = **std::min_element(squad.begin(), squad.end(),
                                       [&](auto a, auto b) { return priority(a) < priority(b); });
    auto &plan = w.at("plans").at(side);
    Tick now = w.at("tick");
    const auto &skills = player_profile(w, captain).at("skills");
    if (plan.at("captain") != captain.at("id")) {
        plan["captain"] = captain.at("id");
        plan["review"] = now + (100 - skills.at("leadership").get<int>()) / 4;
        emit(w, "captain", captain.at("name").get<std::string>() + " принимает колл", side)["player"] =
            captain.at("id");
    }
    if (!plan.contains("economicSightings"))
        plan["economicSightings"] = Json::object();
    auto &economy = plan.at("economicSightings");
    Reports reports, contacts;
    Json ids = Json::array();
    for (const auto &r : captain.at("knowledge")) {
        auto id = r.at("id").get<std::string>();
        if (r.contains("weapon") && !r.at("weapon").empty() &&
            (!economy.contains(id) || economy.at(id).at("tick") < r.at("tick")))
            economy[id] = Json{{"weapon", r.at("weapon")}, {"tick", r.at("tick")}};
        reports.push_back(&r);
        if (r.at("source") != "Слух" && r.at("source") != "Граната" && now - r.at("tick").get<Tick>() <= 74) {
            contacts.push_back(&r);
            ids.push_back(id);
        }
    }
    if (now < plan.at("review").get<Tick>())
        return;
    plan["review"] = now + 18 + (100 - skills.at("calling").get<int>()) / 2;
    if (side == "CT") {
        plan["review"] =
            now + 5 + (200 - skills.at("calling").get<int>() - skills.at("communication").get<int>()) / 8;
        if (w.at("phase") == "live") {
            direct_defense(w, cfg, arena, plan, squad, captain);
            return;
        }
        if (w.at("phase") == "planted" && !captain.at("heardSite").empty()) {
            plan["reinforce"] = captain.at("heardSite");
            if (collective_defense(w) && !arena.objectives().grid())
                review_retake(w, cfg, arena, squad, captain, captain.at("heardSite"));
            else if (!plan.contains("retake"))
                assemble_retake(w, cfg, arena, squad, captain, captain.at("heardSite"));
        }
        return;
    }
    if (collective_attack(w) && !arena.objectives().grid() && plan.value("board", Json(nullptr)).empty()) {
        if (w.at("phase") == "live")
            review_attack(w, cfg, arena, plan, squad, captain, reports);
        return;
    }
    std::string site = plan.at("site"), other = site == "A" ? "B" : "A";
    auto counts = site_pressure(arena, reports, now);
    if (plan.contains("probe") && !plan.at("probe").empty()) {
        auto &probe = plan.at("probe");
        if (!probe.contains("released") || probe.at("released") == 0) {
            bool release = false;
            if (probe.contains("stations")) {
                double travel = 0;
                bool ready = true;
                for (auto a : squad) {
                    travel = std::max(travel, arena.objectives().site_cost(site, a->at("navArea"), 0) /
                                                  (arena.objectives().map().unit() * 1.65));
                    auto id = a->at("id").get<std::string>();
                    ready &= probe.at("reports").contains(id) && probe.at("reports").at(id) <= now;
                }
                release =
                    ready ||
                    (probe.contains("unreachable") &&
                     std::ranges::any_of(probe.at("unreachable"), [&](const Json &t) { return t <= now; })) ||
                    squad.size() <= 3 ||
                    now + travel + cfg.at("rules").at("plant").get<int>() >= probe.at("until").get<Tick>();
            } else
                release =
                    std::ranges::none_of(squad, [&](auto a) { return a->at("id") == probe.at("scout"); }) ||
                    std::ranges::any_of(
                        contacts,
                        [&](auto r) { return arena.objectives().reported_site(actor_point(*r)) == other; }) ||
                    now >= probe.value("reportDue", probe.at("until").get<Tick>()) || squad.size() < 4;
            if (release)
                probe["released"] = now;
        }
    }
    bool obstructed = false;
    if (captain.contains("routeReports"))
        for (auto &row : captain.at("routeReports"))
            obstructed |= row[0] == site && now - row[1].get<Tick>() < 60;
    if (plan.at("rotated") == true || w.at("phase") != "live")
        return;
    if ((!plan.contains("board") || plan.at("board").empty()) &&
        std::ranges::none_of(squad, [](const Json *p) {
            auto &v = p->at("utility");
            return std::find(v.begin(), v.end(), "Дым") != v.end();
        })) {
        const auto &via = plan.at("orders").at("slots").at(captain.at("slot").get<int>()).at("via");
        for (auto r : contacts)
            if (r->value("weapon", std::string{}) == "AWP" && now - r->at("tick").get<Tick>() <= 25)
                for (auto it = via.end() - std::min<std::size_t>(2, via.size()); it != via.end(); ++it) {
                    auto p = actor_point(*r), q = it->get<Point>();
                    double d = distance(p, q);
                    if (d > 30 && d < 100 && !arena.objectives().map().hit(p, q, 1, 64, 64))
                        obstructed = true;
                }
    }
    if ((obstructed ||
         (counts[site] >= std::clamp(squad.size() - .5, 1.5, 2.5) && counts[site] > counts[other])) &&
        now - plan.at("start").get<Tick>() >= (100 - skills.at("adaptability").get<int>()) / 2 &&
        w.at("deadline").get<Tick>() - now > 250) {
        plan["site"] = other;
        plan["rotated"] = true;
        int lane = 1 - plan.at("lane").get<int>();
        plan["lane"] = lane;
        plan["orders"] = arena.attack_orders(w, other, lane, plan.at("style"));
        for (auto a : squad)
            (*a)["waypoint"] = 0;
        emit(w, "rotate",
             captain.at("name").get<std::string>() + " меняет направление после донесения · " + other, "T")
            .update(Json{{"player", captain.at("id")}, {"contacts", ids}});
    }
}
} // namespace esport
