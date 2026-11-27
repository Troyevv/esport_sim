#include "defense_command.hpp"
#include "agent_helpers.hpp"
#include "grid_round.hpp"

namespace esport {
namespace {
const Json &home(const Json &plan, const Json &actor) {
    return plan.at("orders").at("slots").at(actor.at("slot").get<int>());
}

Point forward_post(const OpeningMap &arena, const Json &scout) {
    const auto &nav = arena.objectives().map();
    const Point peek = scout.at("peek"), gate = scout.at("gate"), watch = scout.at("watch");
    auto spots = nearby_points(nav, peek, 23);
    std::erase_if(spots, [&](const Point &p) {
        return distance(p, watch) + 4 >= distance(peek, watch) || distance(p, gate) < 8 ||
               nav.hit(p, gate, 1, 64, 64) || nav.hit(p, watch, 1, 64, 64);
    });
    std::stable_sort(spots.begin(), spots.end(),
                     [&](const Point &a, const Point &b) { return distance(a, watch) < distance(b, watch); });
    return first_reachable(nav, peek, spots).value_or(peek);
}

void reclaim_post(const Json &world, const OpeningMap &arena, Json &plan, const Squad &squad,
                  const std::string &site) {
    if (!active(plan, "backup"))
        return;
    auto &reserve = plan.at("backup");
    const auto &nav = arena.objectives().map();
    auto actor =
        std::find_if(squad.begin(), squad.end(), [&](auto p) { return p->at("id") == reserve.at("id"); });
    if (actor == squad.end())
        return;
    for (const auto &lost : world.at("agents")) {
        if (lost.at("team") != "CT" || lost.at("hp") != 0 || home(plan, lost).at("site") != site ||
            world.at("tick").get<Tick>() - lost.at("lastHurt").get<Tick>() >= 75)
            continue;
        const auto &order = home(plan, lost);
        auto goal = order.at("hold").get<Point>();
        auto watch = order.at("watch").get<Point>();
        if (active(plan, "opening")) {
            const auto &job = plan.at("opening").at("jobs").at(lost.at("id").get<std::string>());
            if (job.contains("gate") && distance(actor_point(lost), job.at("gate")) < 27) {
                goal = job.at("gate");
                watch = job.at("watch");
            }
        }
        if (std::ranges::any_of(squad, [&](auto m) {
                return m != *actor && distance(assignment(plan, *m, squad).at("hold"), goal) < 7;
            }))
            continue;
        auto zone = nav.locate(goal);
        if (zone && nav.path((*actor)->at("navArea"), actor_point(**actor), *zone, goal, {})) {
            reserve.update(
                {{"hold", goal}, {"watch", watch}, {"lane", order.at("lane")}, {"maneuver", "reclaim"}});
            reserve.erase("arriveBy");
            break;
        }
    }
}

// Repeated radio packets about the same obstruction do not create another task.
Json latest_block(const Json &leader, const std::string &site, Tick now) {
    Json block;
    for (auto &[sender, call] : leader.at("sectorCalls").items()) {
        Tick tick = call.at("tick");
        if (call.at("site") == site && call.at("state") == "blocked" && tick <= now && now - tick < 35 &&
            (block.empty() || tick > block.at("tick").get<Tick>()))
            block = {{"sender", sender}, {"point", call.at("point")}, {"tick", tick}};
    }
    return block;
}

struct Option {
    std::string kind, site;
    double score;
};

// Rally points come from reachable NAV surfaces. Keep the rally off the lost
// site and separate teammates who would otherwise stop on the same surface.
Json rally(const OpeningMap &arena, const Json &plan, const Squad &squad, const std::string &site, bool yield,
           bool revised, const Json &leader, Tick now) {
    const auto &nav = arena.objectives().map();
    const Point center = arena.site_point(site);
    Json duties = Json::object();
    Squad local;
    for (auto p : squad)
        if ((yield && arena.objectives().reported_site(actor_point(*p)) == site) ||
            home(plan, *p).at("site") == site || (relief(plan, *p) && relief(plan, *p)->at("site") == site))
            local.push_back(p);
    if (yield && revised)
        std::erase_if(local, [&](auto p) {
            return arena.objectives().reported_site(actor_point(*p)) != site &&
                   distance(actor_point(*p), center) > 55;
        });
    if (local.empty())
        return duties;
    // Regroup on a retained home sector. A wandering wing at the opposite
    // objective must not draw the last local anchor off its site.
    const auto anchor = *std::min_element(local.begin(), local.end(), [&](auto a, auto b) {
        return distance(actor_point(*a), center) < distance(actor_point(*b), center);
    });
    Point back = home(plan, *anchor).at("hold");
    if (!yield)
        std::iter_swap(local.begin(), std::find(local.begin(), local.end(), anchor));
    if (yield) {
        // Prefer the side of the site already accessible to support.
        auto reserve = std::min_element(squad.begin(), squad.end(), [&](auto a, auto b) {
            auto cost = [&](auto p) {
                const double d = distance(actor_point(*p), center);
                return d < 27 ? 10000. : d;
            };
            return cost(a) < cost(b);
        });
        back = actor_point(**reserve);
    }
    for (auto p : local) {
        auto points = nearby_points(nav, yield ? center : back, yield ? 68 : 24);
        if (!yield)
            points.insert(points.begin(), back);
        std::erase_if(points, [&](const Point &q) {
            return (yield && (distance(q, center) < 30 || arena.objectives().site_at(q))) ||
                   std::ranges::any_of(duties, [&](const Json &d) { return distance(q, d.at("hold")) < 7; });
        });
        const Point pos = actor_point(*p);
        auto cost = [&](const Point &q) {
            return distance(q, back) + .45 * distance(q, pos) +
                   (yield && !nav.hit(q, center, 1, 64, 64) ? 24. : 0.);
        };
        std::stable_sort(points.begin(), points.end(), [&](auto &l, auto &r) { return cost(l) < cost(r); });
        if (revised && yield) {
            // Compare short reachable exits by the route actually walked. A wall
            // between the destination and the site does not protect a path through
            // the contact.
            std::vector<std::pair<double, Point>> exits;
            int tested = 0;
            for (const auto &q : points) {
                auto area = nav.locate(q);
                if (!area)
                    continue;
                auto route = nav.path(p->at("navArea"), pos, *area, q, {});
                if (!route)
                    continue;
                double danger = 0;
                for (const auto &r : leader.at("knowledge")) {
                    auto age = now - r.at("tick").get<Tick>();
                    if (!visual(r) || age < 0 || age >= 35 || r.value("disputed", false))
                        continue;
                    const Point contact = actor_point(r);
                    for (auto &[x, y, z, id] : *route) {
                        Point step{x, y, z};
                        if (distance(step, contact) < 33 && !nav.hit(step, contact, 1, 64, 64)) {
                            danger += 30 * (1 - age / 35.);
                            break;
                        }
                    }
                }
                if (!duties.empty() && std::ranges::none_of(duties, [&](const Json &d) {
                        const Point cover = d.at("hold");
                        return distance(cover, q) < 35 && !nav.hit(cover, q, 1, 64, 64);
                    }))
                    danger += 18;
                exits.emplace_back(walk_length(pos, *route) + .35 * cost(q) + danger, q);
                if (++tested == 12)
                    break;
            }
            std::sort(exits.begin(), exits.end());
            points.clear();
            for (const auto &[score, q] : exits)
                points.push_back(q);
        }
        if (auto q = first_reachable(nav, pos, points, p->at("navArea"))) {
            const auto &slot = home(plan, *p);
            Point watch = yield ? center : slot.at("watch").get<Point>();
            if (yield && revised && !duties.empty()) {
                const auto &entry = arena.objectives().ingress().at(site).at(slot.at("lane").get<int>());
                auto visible = std::find_if(entry.begin(), entry.end(), [&](const Point &e) {
                    return distance(*q, e) > 8 && !nav.hit(*q, e, 1, 64, 64);
                });
                if (visible != entry.end())
                    watch = *visible;
            }
            duties[p->at("id").get<std::string>()] = {
                {"id", p->at("id")},
                {"site", site},
                {"hold", *q},
                {"lane", slot.at("lane")},
                {"watch", revised ? Json(watch) : (yield ? Json(center) : slot.at("watch"))},
                {"maneuver", yield ? "yield" : "regroup"}};
            if (revised) {
                auto &duty = duties.at(p->at("id").get<std::string>());
                duty["startPoint"] = pos;
                auto to = nav.locate(*q);
                if (to)
                    if (auto route = nav.path(p->at("navArea"), pos, *to, *q, {}))
                        duty["arriveBy"] = now + Tick(std::ceil(walk_length(pos, *route) / 1.65)) + 12;
            }
        }
    }
    return duties;
}
void issue_defense(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                   const Json &leader, const Pressure &pressure, const Json &bomb, const Json &prior,
                   const Option &best, const Json &pairBySite) {
    const Tick now = w.at("tick");
    const auto priorSite = prior.value("site", std::string{});
    const auto &profile = player_profile(w, leader);
    const int n = int(squad.size());
    const bool changed = best.kind != prior.value("kind", std::string{}) || best.site != priorSite;
    const bool rotated =
        best.kind == "reinforce" || best.kind == "partial" || best.kind == "full" || best.kind == "reclaim";
    const bool gather = best.kind == "regroup" || best.kind == "yield";
    // A different destination cancels the old in-flight reservation. Within a
    // call keep its named player, lane and radio acknowledgements.
    if (changed) {
        if (priorSite != best.site || !rotated || prior.value("kind", std::string{}) == "reclaim") {
            plan.erase("backup");
            plan.erase("secondBackup");
        }
        plan.erase("commitments");
        plan["defenseCall"] = {{"kind", best.kind}, {"site", best.site}, {"issued", now}};
        if (best.kind == "regroup")
            plan["lastRally"][best.site] = {{"alive", n}, {"tick", now}};
        if (best.kind == "regroup" && revised_defense(w))
            plan["lastRally"][best.site]["block"] = latest_block(leader, best.site, now);
        if (rotated || best.kind == "yield")
            plan["lastFront"] = {{"site", best.site}, {"tick", now}};
    }
    plan["reinforce"] = rotated && best.kind != "reinforce" ? Json(best.site) : Json(nullptr);
    if (revised_defense(w)) {
        plan.erase("retainedAnchor");
        if (rotated && best.kind != "full") {
            const std::string other = best.site == "A" ? "B" : "A";
            // Keep control until someone can actually cover the vacated site.
            // Radar distance along NAV breaks ties between assigned home players.
            const Json *anchor = nullptr;
            double cost = 1e9;
            for (auto p : squad) {
                if (home(plan, *p).at("site") != other)
                    continue;
                const auto id = p->at("id").get<std::string>();
                double d = arena.objectives().site_cost(other, p->at("navArea"), 1e8) /
                           arena.objectives().map().unit();
                const auto &calls = leader.at("sectorCalls");
                if (calls.contains(id) && calls.at(id).at("site") == other &&
                    calls.at(id).at("state") == "watching" && now - calls.at(id).at("tick").get<Tick>() < 25)
                    d -= 20;
                if (!anchor || d < cost) {
                    anchor = p;
                    cost = d;
                }
            }
            if (anchor)
                plan["retainedAnchor"] = anchor->at("id");
        }
    }
    if (rotated) {
        if (changed)
            brief_defense(arena, plan, squad, leader, profile, now, w.at("mapId"), true);
        assign_reserves(arena, plan, squad, best.site, pressure, now, bomb,
                        best.kind == "partial" || best.kind == "full" ? 2 : 1);
        if (best.kind == "reclaim" && active(plan, "backup") &&
            !plan.at("backup").contains("reclaimChecked")) {
            reclaim_post(w, arena, plan, squad, best.site);
            plan.at("backup")["reclaimChecked"] = true;
        }
        commit_reserves(arena, plan, squad, best.kind == "full" ? Json(best.site) : Json(nullptr));
    }
    if (best.kind == "save" && changed) {
        const auto &nav = arena.objectives().map();
        const auto center = arena.site_point(best.site);
        const auto pos = actor_point(leader);
        const double radius = cfg.at("blastRadius");
        Point goal = pos;
        if (distance(pos, center) < radius + 4)
            if (auto route = nav.escape(leader.at("navArea"), pos, center, radius + 4);
                route && !route->second.empty()) {
                const auto &[x, y, z, area] = route->second.back();
                goal = {x, y, z};
            }
        plan["commitments"][leader.at("id").get<std::string>()] = {
            {"id", leader.at("id")}, {"site", best.site}, {"lane", home(plan, leader).at("lane")},
            {"hold", goal},          {"watch", center},   {"maneuver", "save"}};
    }
    if (gather && (changed || (!revised_defense(w) && prior.value("alive", 0) != n)))
        plan["commitments"] =
            rally(arena, plan, squad, best.site, best.kind == "yield", revised_defense(w), leader, now);
    if (gather && revised_defense(w)) {
        auto &jobs = plan.at("commitments");
        for (auto it = jobs.begin(); it != jobs.end();)
            if (std::ranges::none_of(squad, [&](auto p) { return p->at("id") == it.key(); }))
                it = jobs.erase(it);
            else
                ++it;
    }
    plan.at("defenseCall")["alive"] = n;
    if (best.kind == "space") {
        const auto &pair = pairBySite.at(best.site);
        auto &call = plan.at("defenseCall");
        if (call.value("pair", Json(nullptr)) != pair) {
            call["pair"] = pair;
            call["post"] =
                forward_post(arena, plan.at("opening").at("jobs").at(pair.front().get<std::string>()));
        }
    }
    if (changed) {
        Json goals = Json::object();
        for (auto p : squad) {
            auto id = p->at("id").get<std::string>();
            if (auto duty = relief(plan, *p))
                goals[id] = duty->at("hold");
            else if (best.kind == "space" && member_of(pairBySite.at(best.site), id)) {
                const auto &job = plan.at("opening").at("jobs").at(id);
                goals[id] = job.at("role") == "разведка" ? plan.at("defenseCall").at("post") : job.at("gate");
            }
        }
        static const std::map<std::string, std::string> labels{
            {"hold", "Сохранить расстановку"},  {"space", "Проверить сектор парой"},
            {"reclaim", "Вернуть сектор"},      {"reinforce", "Поддержать направление"},
            {"partial", "Частичная перетяжка"}, {"full", "Полная перетяжка"},
            {"regroup", "Собраться на рубеже"}, {"yield", "Отдать плент под ретейк"},
            {"save", "Сохранить оружие"}};
        emit(w, "defense_call", labels.at(best.kind) + (best.site.empty() ? "" : " · " + best.site), "CT")
            .update({{"player", leader.at("id")},
                     {"decision", best.kind},
                     {"site", best.site},
                     {"scores", plan.at("defenseScores")},
                     {"pressure", pressure},
                     {"goals", std::move(goals)}});
    }
}
} // namespace

void compare_defense(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                     const Json &leader, const Reports &reports, const Pressure &pressure,
                     const Losses &losses, const Json &bomb, const Json &on_site) {
    const Tick now = w.at("tick"), elapsed = now - plan.at("start").get<Tick>();
    const Tick remaining = w.at("deadline").get<Tick>() - now;
    const auto &profile = player_profile(w, leader), &skills = profile.at("skills");
    const auto prior = plan.value("defenseCall", Json::object());
    const auto age = now - prior.value("issued", Tick{-1000});
    const auto priorSite = prior.value("site", std::string{});
    const int n = int(squad.size());
    int utility = 0, value = 0;
    double fit = 0;
    for (auto p : squad) {
        utility += int(p->at("utility").size());
        value += equipment_value(*p, cfg);
        auto &player = player_profile(w, *p);
        fit += (player.at("roleMastery").value(p->at("playingRole").get<std::string>(), 0) +
                player.at("skills").at("synchronization").get<int>() +
                (p == &leader ? skills.at("leadership").get<int>() : chemistry(w, leader, *p))) /
               300.;
    }
    fit /= n;
    const double aggression = (skills.at("aggression").get<int>() + skills.at("risk").get<int>()) / 200.;
    const double reading = (skills.at("game_reading").get<int>() + skills.at("adaptability").get<int>() +
                            profile.at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0)) /
                           300.;
    const double friction = std::max(0., 1. - age / 55.) * (13. - 5. * reading);
    Json scores = Json::object();
    Option best{"hold", "", -1e9};
    auto offer = [&](std::string kind, std::string site, double benefit, double risk) {
        const bool same = prior.value("kind", std::string{}) == kind && priorSite == site;
        double net = benefit - risk - (same ? 0. : friction);
        scores[kind + (site.empty() ? "" : "/" + site)] = net;
        if (net > best.score)
            best = {kind, site, net};
    };
    offer("hold", "", 32 + skills.at("patience").get<int>() / 14., 0);
    Json pairBySite = Json::object();
    for (std::string site : {"A", "B"}) {
        const std::string other = site == "A" ? "B" : "A";
        const double threat = pressure.at(site), away = pressure.at(other);
        int local = 0, anchors = 0, exposed = 0;
        bool displaced = false, progressing = false, workingPair = false;
        double exposedHealth = 0;
        double health = 0, spread = 0, eta = 10000;
        const Json *first = nullptr;
        for (auto p : squad) {
            if (revised_defense(w)) {
                const auto pos = actor_point(*p);
                const auto &job = home(plan, *p);
                if (arena.objectives().reported_site(pos) == site ||
                    (job.at("site") == site && distance(pos, arena.site_point(site)) <= 55)) {
                    ++exposed;
                    exposedHealth += p->at("hp").get<int>() / 100.;
                }
                if (job.at("site") == site && active(plan, "opening")) {
                    const auto &opening =
                        plan.at("opening").at("jobs").at(p->at("id").template get<std::string>());
                    if (active(opening, "partner") && !active(opening, "withdrawn") &&
                        std::ranges::any_of(squad,
                                            [&](auto m) { return m->at("id") == opening.at("partner"); }) &&
                        ((opening.contains("gate") && distance(pos, opening.at("gate")) < 14) ||
                         (opening.contains("peek") && distance(pos, opening.at("peek")) < 14)))
                        workingPair = true;
                }
                if (job.at("site") == site && arena.objectives().reported_site(pos) == other)
                    displaced = true;
                if (const auto duty = relief(plan, *p);
                    duty && duty->at("site") == site &&
                    duty->value("maneuver", std::string{}) == prior.value("kind", std::string{}) &&
                    (duty->value("acknowledged", std::string{}) == "moving" ||
                     (duty->contains("startPoint") && distance(pos, duty->at("startPoint")) > 3)) &&
                    distance(pos, duty->at("hold")) > 8 &&
                    plan.at("unavailable").value(p->at("id").template get<std::string>(), std::string{}) !=
                        site &&
                    now <= duty->value("arriveBy", now))
                    progressing = true;
            }
            if (home(plan, *p).at("site") == site) {
                ++local;
                health += p->at("hp").get<int>() / 100.;
                if (first)
                    spread = std::max(spread, distance(actor_point(*p), actor_point(*first)));
                else
                    first = p;
            }
            if (home(plan, *p).at("site") != site && p->at("slot") != 4)
                ++anchors;
            if (p->at("slot") == 4 || home(plan, *p).at("site") != site)
                eta = std::min(
                    eta, arena.objectives().site_cost(site, p->at("navArea"), 1e6) /
                             (arena.objectives().map().unit() * 1.65 * move_speed(player_profile(w, *p))));
        }
        int seen = 0, reportedGroup = 0;
        Tick newest = -1;
        for (auto r : reports) {
            if (now - r->at("tick").get<Tick>() >= 45 || !visual(*r) ||
                arena.objectives().reported_site(actor_point(*r)) != site)
                continue;
            ++seen;
            reportedGroup = std::max(reportedGroup, r->value("groupSize", 1));
            newest = std::max(newest, r->at("tick").get<Tick>());
        }
        seen = std::max(seen, reportedGroup);
        bool recoveredContact = false, requestedHelp = false;
        for (const auto &kill : w.at("kills")) {
            if (now - kill.at("tick").get<Tick>() >= 35)
                continue;
            auto report = leader.at("knowledge").find(kill.at("target").get<std::string>());
            if (report != leader.at("knowledge").end() && visual(*report) &&
                !report->value("disputed", false) && report->at("tick") <= kill.at("tick") &&
                kill.at("tick").get<Tick>() - report->at("tick").get<Tick>() < 20 &&
                arena.objectives().reported_site(actor_point(*report)) == site)
                recoveredContact = true;
        }
        for (const auto &call : leader.at("squadPressure"))
            if (now >= call.at("tick").get<Tick>() && now - call.at("tick").get<Tick>() < 30 &&
                arena.objectives().reported_site(call.at("origin")) == site)
                requestedHelp = true;
        const int lost = int(losses.at(site).size());
        const bool evidence = seen || lost;
        const bool changedFront = plan.contains("lastFront") && plan.at("lastFront").at("site") != site;
        const bool fresh =
            !changedFront || newest > plan.at("lastFront").at("tick").get<Tick>() ||
            (!losses.at(site).empty() && *std::max_element(losses.at(site).begin(), losses.at(site).end()) >
                                             plan.at("lastFront").at("tick").get<Tick>());
        const double travel = std::min(17., eta / 8.);
        auto available = [&](const Json *p) {
            const auto &slot = home(plan, *p);
            const auto id = p->at("id").template get<std::string>();
            if ((p->at("slot") != 4 && slot.at("site") == site) ||
                plan.at("unavailable").value(id, std::string{}) == site)
                return false;
            return slot.at("site") == site || std::ranges::any_of(squad, [&](auto mate) {
                       return mate != p && home(plan, *mate).at("site") != site;
                   });
        };
        const bool hasReserve = std::ranges::any_of(squad, available);
        const bool mobile =
            std::ranges::any_of(squad, [&](auto p) { return p->at("slot") == 4 && available(p); });
        const bool help = eta < remaining && fresh && (evidence || requestedHelp || threat >= .8);
        if (help && n > 1 && hasReserve && (mobile || threat >= 1.65)) {
            offer("reinforce", site,
                  33 + 8 * std::min(3., threat) + 6 * reading + 6 * lost + 8 * requestedHelp,
                  travel + 7 * away + 6 * !evidence);
            if (evidence && threat >= 2 && anchors >= 2)
                offer("partial", site, 31 + 10 * std::min(4., threat) + 7 * fit, travel + 11 * away);
        }
        // Let an acknowledged reserve finish a short move while its original
        // observation fades. Silence cannot renew this commitment.
        if (priorSite == site && prior.value("kind", std::string{}) == "reinforce" && age < 38 &&
            away < .65 && active(plan, "backup")) {
            const auto &duty = plan.at("backup");
            const std::string who = duty.at("id");
            if (duty.value("acknowledged", std::string{}) == "moving" && duty.value("arriveBy", now) >= now &&
                std::ranges::any_of(squad, [&](auto p) { return p->at("id") == who; }) &&
                plan.at("unavailable").value(who, std::string{}) != site) {
                auto key = "reinforce/" + site;
                if (!scores.contains(key) || scores.at(key) < 40.)
                    offer("reinforce", site, 40, 0);
            }
        }
        if (help && local < n && (on_site == site || (bomb == site && seen >= 2 && threat >= 2.8)))
            offer("full", site, 64 + 7 * threat + 6 * reading, travel + 6 * away);
        if ((lost || (recoveredContact && local < 2)) && n >= 2 && fresh && eta < remaining && threat < 3.2 &&
            hasReserve)
            offer("reclaim", site, 57 + 8 * lost + 5 * fit, travel + 5 * seen + 5 * away);
        if (revised_defense(w))
            health = exposedHealth;
        if (fresh && (revised_defense(w) ? exposed : local) && n > 1 && seen >= 2 && health + .35 < seen &&
            (bomb == site || lost))
            offer("yield", site, 66 + 10 * (seen - health) + 7 * fit,
                  8 * aggression + std::min(8, utility) + 4 * (on_site != site));
        if (revised_defense(w) && progressing && priorSite == site && prior.at("kind") == "yield" &&
            away < 1 && on_site != other && !scores.contains("yield/" + site))
            offer("yield", site, 41 + std::min(2., threat) * 5, away * 5);
        // Saving during live play requires a witnessed objective and a
        // meaningful purchase to carry forward. A late noise is insufficient.
        if (fresh && n == 1 && seen >= 2 && on_site == site &&
            remaining > cfg.at("rules").at("plant").get<int>() && value >= 2300 && leader.at("hp") < 45) {
            offer("save", site, 65 + 5 * seen + std::min(18., value / 300.),
                  leader.at("hp").get<int>() / 4. + 12 * aggression);
        }
        // Split opening assignments are intentional. Reopen a completed rally
        // only after another loss or a new report of a blocked local route.
        Tick blocked = -1;
        for (const auto &call : leader.at("sectorCalls"))
            if (call.at("site") == site && call.at("state") == "blocked" &&
                now - call.at("tick").get<Tick>() < 35)
                blocked = std::max(blocked, call.at("tick").get<Tick>());
        const auto rallies = plan.find("lastRally");
        const bool continuingRally = prior.value("kind", std::string{}) == "regroup" && priorSite == site;
        bool newRally = rallies == plan.end() || !rallies->contains(site) ||
                        rallies->at(site).at("alive") != n ||
                        blocked > rallies->at(site).at("tick").get<Tick>();
        const bool localLoss =
            !losses.at(site).empty() && (rallies == plan.end() || !rallies->contains(site) ||
                                         *std::max_element(losses.at(site).begin(), losses.at(site).end()) >
                                             rallies->at(site).at("tick").get<Tick>());
        if (revised_defense(w) && rallies != plan.end() && rallies->contains(site)) {
            const auto &last = rallies->at(site);
            const auto block = latest_block(leader, site, now);
            const auto previous = last.value("block", Json(nullptr));
            const bool different = !block.empty() && block.at("tick") > last.at("tick") &&
                                   (previous.empty() || previous.at("sender") != block.at("sender") ||
                                    distance(previous.at("point"), block.at("point")) > 10);
            newRally = localLoss || different ||
                       (displaced && plan.contains("lastFront") &&
                        plan.at("lastFront").at("tick") > last.at("tick"));
        }
        const bool disrupted =
            !revised_defense(w) ||
            (continuingRally ? progressing || displaced
                             : ((!workingPair || localLoss) && (displaced || localLoss || blocked >= 0)));
        if (disrupted && local >= 2 && n < 5 && spread > (continuingRally ? 28 : 58) && threat < 2 &&
            elapsed > 60 && (continuingRally || newRally))
            offer("regroup", site, 35 + std::min(15., spread / 10.) + 10 * fit, 6 * threat + 3 * aggression);
        // Reuse the opening's validated gate, observer and escort. Permission
        // ends when the pair breaks up or pressure rises.
        const bool keepingSpace = prior.value("kind", std::string{}) == "space" && priorSite == site;
        if (n >= 3 && active(plan, "opening") && elapsed >= 35 && remaining > 140 &&
            threat + away < (keepingSpace ? 1.65 : 1.1)) {
            const auto &jobs = plan.at("opening").at("jobs");
            for (auto p : squad) {
                auto id = p->at("id").get<std::string>();
                const auto &j = jobs.at(id);
                if (j.at("site") != site || j.at("role") != "разведка" || !active(j, "partner") ||
                    active(j, "withdrawn") || (!keepingSpace && j.value("rechecks", 0) > 0))
                    continue;
                if (std::ranges::none_of(squad, [&](auto m) {
                        return m->at("id") == j.at("partner") && m->at("hp") >= 35 &&
                               !active(jobs.at(m->at("id").template get<std::string>()), "withdrawn");
                    }))
                    continue;
                pairBySite[site] = Json::array({id, j.at("partner")});
                offer("space", site, 17 + 25 * aggression + 10 * fit + 6 * reading,
                      4 * (value / n > 4000) + 10 * threat);
                break;
            }
        }
    }
    plan["defenseScores"] = std::move(scores);
    issue_defense(w, cfg, arena, plan, squad, leader, pressure, bomb, prior, best, pairBySite);
}
} // namespace esport
