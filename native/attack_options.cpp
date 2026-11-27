#include "attack_options.hpp"
#include "agent_helpers.hpp"
#include "grid_round.hpp"
#include <algorithm>
#include <string_view>

namespace esport {
namespace {
struct Candidate {
    const char *name;
    double benefit, risk;
    bool possible;
};

const Json *feedback(const Json &captain, const Json &mate, std::string channel, Tick now) {
    const bool own = &captain == &mate;
    auto inbox = captain.find(own ? "sentFeedback" : "peerCalls");
    if (inbox == captain.end())
        return nullptr;
    auto msg = inbox->find(own ? channel : mate.at("id").get<std::string>() + "/" + channel);
    return msg != inbox->end() && now >= msg->at("tick") && now - msg->at("tick").get<Tick>() < 35 ? &*msg
                                                                                                   : nullptr;
}

// A route change invalidates stage invitations. Contact assistance and actual
// projectiles have their own lifetimes and remain valid across revisions.
void new_route(Json &a, Tick now) {
    a["routeIssued"] = now;
    a["path"] = Json::array();
    a["dest"] = nullptr;
    for (auto key : {"attackGate", "revisedApproach", "rendezvous", "plantSpot"})
        a.erase(key);
    if (active(a, "pendingFlash")) {
        const auto &cast = a.at("pendingFlash").at("target");
        if (cast.value("purpose", "") == "Ложный выход" ||
            (cast.contains("groupTicket") && cast.at("groupTicket").at(1) == "stage"))
            a.erase("pendingFlash");
    }
}

Json job(const Point &point, const Point &watch, const std::string &site) {
    return {{"point", point}, {"watch", watch}, {"site", site}};
}

Json rally_jobs(const OpeningMap &arena, const Squad &squad, const Json &orders, const Json &anchor,
                const std::string &site) {
    Json jobs = Json::object();
    const auto &nav = arena.objectives().map();
    for (auto a : squad) {
        const auto &order = orders.at("slots").at(a->at("slot").get<int>());
        const Json *mate = &anchor;
        // A dispersed second pair can keep its own lane. The member nearer
        // the objective holds that position while its partner closes the gap.
        for (auto p : squad) {
            const auto &other = orders.at("slots").at(p->at("slot").get<int>());
            if (p != a && p != &anchor && other.at("lane") == order.at("lane") &&
                other.at("lane") != orders.at("slots").at(anchor.at("slot").get<int>()).at("lane") &&
                distance(actor_point(*p), actor_point(*a)) < distance(actor_point(anchor), actor_point(*a))) {
                mate = travel_ticks(arena, site, p->at("navArea")) < travel_ticks(arena, site, a->at("navArea"))
                           ? p
                           : a;
                break;
            }
        }
        const Point pos = actor_point(*a), center = actor_point(*mate);
        Point goal = pos;
        if (distance(pos, center) > 20 ||
            std::ranges::any_of(jobs, [&](const Json &j) { return distance(pos, j.at("point")) < 6; })) {
            auto options = nearby_points(nav, center, 23);
            std::erase_if(options, [&](const Point &q) {
                return distance(q, center) < 8 || nav.hit(q, center, 1, 64, 64) ||
                       std::ranges::any_of(jobs, [&](const Json &j) { return distance(q, j.at("point")) < 6; });
            });
            std::stable_sort(options.begin(), options.end(),
                             [&](const auto &l, const auto &r) { return distance(l, pos) < distance(r, pos); });
            goal = first_reachable(nav, pos, options, a->at("navArea")).value_or(pos);
        }
        jobs[a->at("id").get<std::string>()] = job(goal, order.at("watch"), site);
    }
    return jobs;
}
Json feint_jobs(const Json &w, const OpeningMap &arena, const Squad &squad, const Json *carrier,
                const std::string &other, int lane) {
    Json jobs = Json::object();
    const auto &nav = arena.objectives().map();
    const auto alternateOrders = arena.attack_orders(w, other, lane, "Сбор");
    auto wing = squad;
    std::erase(wing, carrier);
    std::stable_sort(wing.begin(), wing.end(), [&](auto l, auto r) {
        auto cost = [&](auto a) {
            return travel_ticks(arena, other, a->at("navArea")) - 10 * (a->at("playingRole") == "lurker") -
                   4 * int(a->at("utility").size());
        };
        return cost(l) < cost(r);
    });
    const auto &lead = alternateOrders.at("slots").at(wing.front()->at("slot").get<int>());
    const Point stage = lead.at("stage");
    for (int i = 0; i < 2; ++i) {
        auto a = wing[i];
        Point goal = stage;
        if (i) {
            auto spots = nearby_points(nav, stage, 18);
            std::erase_if(
                spots, [&](const Point &p) { return distance(p, stage) < 6 || nav.hit(p, stage, 1, 64, 64); });
            goal = first_reachable(nav, actor_point(*a), spots, a->at("navArea")).value_or(stage);
        }
        jobs[a->at("id").get<std::string>()] = job(goal, lead.at("watch"), other);
        jobs.at(a->at("id").get<std::string>())["lane"] = lead.at("lane");
    }
    return jobs;
}
} // namespace

void compare_attack(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                    const Json &captain, const Json *carrier, const Reports &reports, const Pressure &pressure,
                    SectorCounts &held, SectorCounts &blocked, bool probing) {
    const Tick now = w.at("tick"), remaining = w.at("deadline").get<Tick>() - now;
    const std::string site = plan.at("site"), other = site == "A" ? "B" : "A";
    const auto &skills = player_profile(w, captain).at("skills");
    const Json *rallyAnchor = carrier ? carrier : &captain;
    const auto &bomb = w.at("bomb");
    if (!carrier && active(bomb, "recovery"))
        for (const auto *mate : squad)
            if (mate->at("id") == bomb.at("recovery").at("player"))
                rallyAnchor = mate;
    const Json &anchor = *rallyAnchor;
    const auto area = anchor.at("navArea").get<AreaId>();
    const double travel = std::min(1500., travel_ticks(arena, site, area));
    const double alternate = std::min(1500., travel_ticks(arena, other, area));
    const int plant = cfg.at("rules").at("plant"), n = int(squad.size());
    const double slack = remaining - plant - travel;
    const double progress = std::clamp(1. - travel / 85., 0., 1.);
    const double urgency = std::clamp((110. - slack) / 100., 0., 1.);
    int unsupported = 0, supplies = 0, guns = 0, acknowledged = 0;
    double spread = 0, teamFit = 0;
    for (auto a : squad) {
        double nearest = 1000;
        for (auto p : squad)
            if (p != a)
                nearest = std::min(nearest, distance(actor_point(*p), actor_point(*a)));
        unsupported += n > 1 && nearest > 34;
        spread = std::max(spread, distance(actor_point(*a), actor_point(anchor)));
        supplies += int(a->at("utility").size());
        guns += equipment_value(*a, cfg) >= 2200;
        const auto &profile = player_profile(w, *a);
        teamFit += (profile.at("roleMastery").value(a->at("playingRole").get<std::string>(), 0) +
                    profile.at("skills").at("synchronization").get<int>() +
                    (a == &captain ? skills.at("leadership").get<int>() : chemistry(w, captain, *a))) /
                   300.;
        if (const auto *msg = feedback(captain, *a, "order", now)) {
            const auto &order = msg->at("order");
            if (order.is_array() && order.size() >= 4 && order.back() == plan.value("revision", 0)) {
                unsupported += msg->at("state") == "unavailable" || msg->at("state") == "refused";
                ++acknowledged;
            }
        }
    }
    teamFit /= n;
    const auto lastTurn = plan.value("lastDirection", Tick{-10000});
    // Require positive evidence at the currently called site since the last
    // switch. Decay of old reports on the other site cannot cause a reversal.
    Reports fresh;
    for (auto r : reports)
        if (r->at("tick") > lastTurn && now >= r->at("tick") && r->value("confidence", 1.) >= .40 &&
            !r->value("disputed", false))
            fresh.push_back(r);
    bool newBlock = false;
    for (const auto &r : captain.at("routeReports"))
        newBlock |= r[0] == site && r[1] > lastTurn && r[1] <= now && now - r[1].get<Tick>() < 45;
    for (auto a : squad)
        if (auto msg = feedback(captain, *a, "sector", now))
            newBlock |= msg->at("order") == site && msg->at("state") != "held" && msg->at("tick") > lastTurn;
    const double confirmed = site_pressure(arena, fresh, now).at(site);
    const double resistance = pressure.at(site), elsewhere = pressure.at(other);
    const double disorder =
        std::min(3., unsupported * .65 + std::min(2, blocked[site]) * .75 +
                         1.4 * std::clamp((spread - 40) / 80., 0., 1.) + (!carrier ? 1. : 0.));
    const double elapsed = now - plan.at("start").get<Tick>();
    const double infoNeed = std::clamp(1. - (held[site] + held[other] + resistance + elsewhere) / 4., 0., 1.);
    const double calling =
        (skills.at("calling").get<int>() +
         player_profile(w, captain).at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0)) /
        200.;
    const std::string prior = plan.value("commandKind", std::string{});
    const Tick since = plan.value("issued", plan.at("start").get<Tick>());
    const double switchCost = std::clamp(1. - double(now - since) / 55., 0., 1.) * (prior.empty() ? 0. : 14.);
    const bool timeToPlay = slack > 65 && carrier;
    const bool freshRead = confirmed >= .8 || newBlock;
    const bool paired = n >= 4;
    const bool feintWindow = prior == "feint" ? now - since < 68 && elsewhere < 1.7
                                              : (probing || (held[other] > 0 && freshRead)) && elapsed > 24 &&
                                                    now - plan.value("feintEnd", Tick{-1000}) > 75;
    const auto rally = plan.value("lastRally", Json::object());
    // A completed rally answers the disruption that caused it. Mere passage
    // of time cannot turn the same detached wing into another emergency.
    const bool disruption = rally.empty() || n < rally.at("alive") || blocked[site] > rally.at("blocked") ||
                            disorder > rally.at("disorder").get<double>() + .65 ||
                            (rally.at("hasC4") == true && !carrier);
    const bool rallyWindow = prior == "regroup" ? now - since < 45 : disruption;
    const bool intendedSpread = prior == "feint" && paired && now - since < 68 && !blocked[site] && carrier;
    const bool spaceWindow = probing && timeToPlay && n >= 3 && now < plan.at("probe").at("until") &&
                             (prior != "space" || now - since < 45);
    // Comparable utility units. Costs cover objective time, resistance,
    // formation disruption and the equipment potentially lost next round.
    Candidate candidates[] = {
        {"continue", 42 + 9 * progress + 8 * held[site], 4 * resistance, true},
        {"fast", 36 + 48 * urgency + 5 * held[site] + 5 * (guns == 0), 5 * resistance + 3 * unsupported,
         bool(carrier)},
        {"slow", 32 + 15 * std::min(1.4, resistance) + 6 * infoNeed, 12 * urgency + 7 * progress,
         timeToPlay && resistance > .2},
        {"scout", 43 + 27 * infoNeed + 6 * calling, elapsed * .22 + 5 * resistance, probing && timeToPlay},
        {"space", 43 + 10 * infoNeed + 9 * teamFit + 6 * std::min(2, held[site] + held[other]),
         7 * resistance + std::max(0., elapsed - 100.) * .25, spaceWindow},
        {"regroup", 25 + 23 * disorder + 7 * (5 - n), 15 * progress + 10 * urgency,
         rallyWindow && !intendedSpread && remaining > plant + 40 && disorder > .65},
        {"rotate", 35 + 28 * (resistance - elsewhere) + 38 * (newBlock && !blocked[other]) + 6 * held[other],
         16 * progress + std::max(0., alternate - travel) * .09 +
             std::max(0., 75. - double(now - lastTurn)) * .35 + (1. - calling) * 9,
         carrier && freshRead && remaining > alternate + plant + 30},
        {"feint", 33 + 14 * teamFit + 7 * calling + std::min(supplies, 6) * 2. + 5 * held[other],
         8 * elsewhere + 10 * urgency + 9 * unsupported, paired && timeToPlay && feintWindow},
        {"split", 32 + 15 * teamFit + 4 * std::min(2, held[site]) + 8 * std::min(1., resistance),
         9 * urgency + 5 * unsupported, paired && timeToPlay && (!probing || held[site] + held[other] >= 2)},
        {"save", 13 + 24. * guns / n + 17 * std::max(0., resistance - n + 1) + 55 * (slack < 0 || !carrier),
         22 * progress + 22 * (slack > 60 && carrier), guns > 0 && (!carrier || slack < 55 || n <= 2)}};
    const Candidate *best = nullptr;
    double value = -1e9;
    Json scores = Json::object();
    for (const auto &c : candidates) {
        if (!c.possible)
            continue;
        const bool keepsRoute = prior == c.name || (prior == "rotate" && std::string_view(c.name) == "continue");
        double net = c.benefit - c.risk - (keepsRoute ? 0. : switchCost);
        scores[c.name] = net;
        if (net > value) {
            best = &c;
            value = net;
        }
    }
    const std::string choice = best->name;
    plan["assessment"] = {
        {"tick", now}, {"scores", scores}, {"acknowledged", acknowledged}, {"choice", choice}};
    if (choice == prior && choice != "rotate")
        return;

    const auto oldJobs = plan.value("commandJobs", Json::object());
    Json jobs = Json::object();
    const auto &nav = arena.objectives().map();
    const auto lane = plan.at("lane").get<int>();
    const bool turn = choice == "rotate";
    const std::string target = turn ? other : site;
    const bool reform = turn || (choice == "split" && plan.at("style") == "Групповой выход");
    if (reform) {
        plan["lane"] = turn ? 1 - lane : lane;
        plan["orders"] = arena.attack_orders(w, target, plan.at("lane"), "Сбор");
    }
    if (choice == "regroup")
        jobs = rally_jobs(arena, squad, plan.at("orders"), anchor, site);
    if (choice == "feint") {
        jobs = feint_jobs(w, arena, squad, carrier, other, lane);
        for (auto a : squad)
            if (jobs.contains(a->at("id").get<std::string>()))
                a->erase("feintThrown");
    }
    if (choice == "space" || choice == "save") {
        for (auto a : squad) {
            const auto &order = plan.at("orders").at("slots").at(a->at("slot").get<int>());
            if (choice == "space") {
                if (a == carrier || distance(actor_point(*a), order.at("stage")) < 6)
                    continue;
                jobs[a->at("id").get<std::string>()] = job(order.at("stage"), order.at("watch"), site);
                break;
            }
            std::vector<Point> spots;
            for (auto id : arena.layout().attack_spawns) {
                const auto point = nav.center(id);
                if (std::ranges::none_of(jobs,
                                         [&](const Json &j) { return distance(point, j.at("point")) < 4; }))
                    spots.push_back(point);
            }
            const Point pos = actor_point(*a);
            std::stable_sort(spots.begin(), spots.end(),
                             [&](auto &l, auto &r) { return distance(l, pos) < distance(r, pos); });
            jobs[a->at("id").get<std::string>()] =
                job(first_reachable(nav, pos, spots, a->at("navArea")).value_or(pos), order.at("watch"), site);
        }
    }
    if (prior == "feint")
        plan["feintEnd"] = now;
    if (choice == "regroup")
        plan["lastRally"] = {{"alive", n},
                             {"disorder", disorder},
                             {"blocked", blocked[site]},
                             {"hasC4", carrier != nullptr}};
    if (turn) {
        plan["site"] = target;
        plan["rotated"] = true;
        plan["lastDirection"] = now;
    }
    const bool release = probing && choice != "space" && choice != "scout";
    if (release)
        plan.at("probe")["released"] = now;
    if (reform || release)
        resume_routes(arena, plan, squad);
    for (auto a : squad) {
        auto id = a->at("id").get<std::string>();
        if (reform || release || oldJobs.contains(id) || jobs.contains(id)) {
            new_route(*a, now);
            plan["routeChanges"][id] = now;
        }
    }
    if (choice == "fast")
        plan["style"] = "Быстро";
    else if (choice == "split" || choice == "slow" || prior == "fast")
        plan["style"] = "Сбор";
    plan["commandJobs"] = std::move(jobs);
    plan["commandKind"] = choice;
    plan["issued"] = now;
    const int revision = plan.value("revision", 0) + 1;
    plan["revision"] = revision;
    static const std::map<std::string, std::string> labels{{"rotate", "Меняет плент"},
                                                           {"split", "Выход с двух входов"},
                                                           {"regroup", "Перестроиться по парам"},
                                                           {"scout", "Продолжить разведку"},
                                                           {"space", "Занять рубеж"},
                                                           {"fast", "Ускорить выход"},
                                                           {"slow", "Замедлить выход"},
                                                           {"save", "Сохранить оружие"},
                                                           {"continue", "Продолжить выход"},
                                                           {"feint", "Ложный выход пары"}};
    auto &event = emit(w, turn ? "rotate" : "command",
                       captain.at("name").get<std::string>() + " · " + labels.at(choice) + " · " + target, "T");
    event.update({{"player", captain.at("id")},
                  {"choice", choice},
                  {"site", target},
                  {"from", site},
                  {"revision", revision},
                  {"scores", scores},
                  {"acknowledged", acknowledged},
                  {"freshPressure", confirmed},
                  {"freshBlock", newBlock},
                  {"alternateTravel", alternate},
                  {"remaining", remaining},
                  {"pressure", pressure},
                  {"blocked", blocked},
                  {"held", held}});
}
} // namespace esport
