#include "radio.hpp"
#include "defense_command.hpp"
#include <algorithm>
#include <cmath>

namespace esport {
namespace {
bool direct_sight(const Json &s) { return s.at("source") == "Зрение" || s.at("source") == "Радио"; }
bool in_view(const Json &a, const Point &q) {
    auto p = actor_point(a);
    double x = q[0] - p[0], y = q[1] - p[1], h = a.at("heading"), d = x * std::cos(h) + y * std::sin(h);
    return d >= 0 && 4 * d * d >= x * x + y * y;
}
bool facing(const Point &p, const Point &w, const Point &q) {
    double a = w[0] - p[0], b = w[1] - p[1], x = q[0] - p[0], y = q[1] - p[1];
    return a * x + b * y >= .5 * std::hypot(a, b) * std::hypot(x, y);
}
bool truth(const Json &j, const std::string &key) {
    return j.contains(key) && !j.at(key).empty() && j.at(key) != false && j.at(key) != 0;
}
} // namespace
void brief_defense(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &leader,
                   const Json &player, Tick now, const std::string &map, bool peers) {
    const auto &nav = arena.objectives().map();
    auto &skills = player.at("skills");
    int familiar = player.at("mapKnowledge").value(map.substr(3), 0), base = plan.at("lane");
    Json lanes = Json::object();
    for (std::string site : {"A", "B"}) {
        std::array<double, 2> scores{};
        for (int lane : {0, 1}) {
            auto &route = arena.objectives().ingress().at(site).at(lane);
            if (route.empty())
                continue;
            std::set<Point> covered;
            for (auto mate : squad) {
                const auto &order = assignment(plan, *mate, squad);
                if (order.at("site") != site || order.value("lane", lane) != lane)
                    continue;
                const auto calls = leader.value("sectorCalls", Json::object());
                auto id = mate->at("id").get<std::string>();
                if (calls.contains(id)) {
                    const auto &call = calls.at(id);
                    auto age = now - call.at("tick").get<Tick>();
                    if (call.at("site") == site && call.at("lane") == lane && age >= 0 && age < 35) {
                        if (call.at("state") == "watching")
                            covered.insert(call.at("point").get<Point>());
                        continue;
                    }
                }
                if (peers && mate != &leader)
                    continue;
                auto hold = order.at("hold").get<Point>(), watch = order.at("watch").get<Point>();
                if (distance(actor_point(*mate), hold) < 8 && mate->at("reloadAt") == 0) {
                    for (auto &p : route)
                        if (facing(hold, watch, p) && !nav.hit(hold, p, 1, 64, 64) && in_view(*mate, p))
                            covered.insert(p);
                    if (in_view(*mate, watch))
                        covered.insert(watch);
                }
            }
            double evidence = 0;
            for (auto &r : leader.at("knowledge")) {
                auto age = now - r.at("tick").get<Tick>();
                if (age < 0 || age >= 75)
                    continue;
                auto pos = actor_point(r);
                auto q = *std::min_element(route.begin(), route.end(), [&](auto &a, auto &b) {
                    return distance(a, pos) < distance(b, pos);
                });
                double gap = distance(pos, q), movement = 0;
                if (truth(r, "direction")) {
                    auto d = r.at("direction").get<Point>();
                    movement = sum3((q[0] - pos[0]) * d[0], (q[1] - pos[1]) * d[1], (q[2] - pos[2]) * d[2]) /
                               std::max(1., gap);
                }
                double confidence = (1 - age / 75.) / (1 + gap);
                if (r.at("source") == "Граната" || r.at("source") == "Слух")
                    confidence /= 2;
                evidence += confidence * (1 + movement * skills.at("game_reading").get<int>() / 100);
            }
            auto count =
                std::count_if(route.begin(), route.end(), [&](auto &p) { return covered.contains(p); });
            scores[lane] =
                evidence +
                (1 - double(count) / route.size()) *
                    (familiar + skills.at("calling").get<int>() + skills.at("leadership").get<int>()) / 300;
        }
        lanes[site] = scores[1 - base] > scores[base] ? 1 - base : base;
    }
    plan["reliefLanes"] = std::move(lanes);
}
void review_opening(const OpeningMap &arena, Json &plan, const Squad &squad, Tick now, const Json &captain, bool clear_replacement) {
    if (!truth(plan, "opening"))
        return;
    auto &op = plan.at("opening"), &jobs = op.at("jobs");
    std::set<std::string> clear;
    auto actor = [&](const std::string &id) -> Json * {
        for (auto p : squad)
            if (p->at("id") == id)
                return p;
        return nullptr;
    };
    for (auto it = op.at("reports").begin(); it != op.at("reports").end(); ++it) {
        auto age = now - it->at("due").get<Tick>();
        if (!actor(it.key()) || age < 0 || age >= 65)
            continue;
        if (std::ranges::none_of(captain.at("knowledge"), [&](const Json &s) {
                return s.at("tick") >= it->value("observed", it->at("due").get<Tick>()) && direct_sight(s) &&
                       distance(actor_point(s), jobs.at(it.key()).at("watch").get<Point>()) < 28;
            }))
            clear.insert(it.key());
    }
    for (auto p : squad) {
        auto id = p->at("id").get<std::string>();
        auto &j = jobs.at(id);
        auto partner = j.value("partner", std::string{});
        auto mate = actor(partner);
        bool lost =
            !partner.empty() && (!mate || relief(plan, *mate) || truth(jobs.at(partner), "withdrawn"));
        if (truth(j, "handoff") && (clear.contains(partner) || lost)) {
            if (j.contains("throw") && !j.at("throw").contains("land"))
                j.at("throw")["skip"] = "Приказ о смене позиции";
            auto next = j.at("handoff");
            j.erase("handoff");
            j.update(next);
            j["role"] = "наблюдение";
            j["handoffAt"] = now;
            for (auto k : {"partner", "atGate", "lastCover", "departed"})
                j.erase(k);
            jobs.at(partner).erase("partner");
            jobs.at(partner)["holdsFor"] = id;
        }
        if (op.at("quiet") == true && !clear.contains(id) && !relief(plan, *p)) {
            auto &focus = op.at("focus");
            if (focus.size() > 1 && std::find(focus.begin() + 1, focus.end(), j.at("zone")) != focus.end() &&
                std::ranges::any_of(
                    clear, [&](auto &pid) { return op.at("reports").at(pid).at("zone") == focus[0]; }) &&
                !j.contains("release"))
                j["release"] = now;
        }
        auto assigned = actor(j.value("replacement", std::string{}));
        if (assigned) {
            auto &job = jobs.at(assigned->at("id").get<std::string>());
            if (job.contains("coverOrder") && job.at("coverOrder").at("forPlayer") == id) {
                if (lost && now < job.at("coverOrder").at("until").get<Tick>() && !relief(plan, *assigned))
                    continue;
                job.erase("coverOrder");
                if (clear_replacement) j.erase("replacement");
            }
        }
        if (!lost || !j.contains("gate") || relief(plan, *p) || truth(j, "withdrawn"))
            continue;
        auto gate = j.at("gate").get<Point>();
        Json *best = nullptr;
        double gap = 65;
        for (auto m : squad) {
            auto who = m->at("id").get<std::string>();
            auto &job = jobs.at(who);
            double d = distance(actor_point(*m), gate);
            if (m != p && clear.contains(who) && !truth(job, "partner") && !relief(plan, *m) &&
                !truth(job, "coverOrder") && job.at("site") == j.at("site") && d < gap) {
                best = m;
                gap = d;
            }
        }
        if (best) {
            auto &nav = arena.objectives().map();
            auto pos = actor_point(*best);
            auto from = nav.locate(pos), to = nav.locate(gate);
            if (from && to && nav.path(*from, pos, *to, gate, {})) {
                auto who = best->at("id").get<std::string>();
                jobs.at(who)["coverOrder"] =
                    Json{{"goal", gate},    {"watch", j.at("peek")}, {"until", now + 50},
                         {"forPlayer", id}, {"issued", now},         {"captain", captain.at("id")}};
                j["replacement"] = who;
            }
        }
    }
    for (auto &job : jobs)
        if (job.contains("coverOrder") && job.at("coverOrder").at("until") <= now)
            job.erase("coverOrder");
}
void direct_defense(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                    Json &leader) {
    Tick now = w.at("tick");
    const auto &sites = arena.objectives();
    std::set<std::string> dead;
    for (auto &k : w.at("kills"))
        dead.insert(k.at("target"));
    Reports reports, calls;
    const bool ranked = collective_defense(w) && !truth(plan, "board");
    for (auto &r : leader.at("knowledge"))
        if ((!ranked ||
             (!r.value("disputed", false) && r.value("confidence", 1.) >= .35 && r.at("tick") <= now)) &&
            !dead.contains(r.at("id").get<std::string>()))
            reports.push_back(&r);
    if (revised_defense(w) && ranked) {
        std::erase_if(reports, [&](auto r) {
            // A later clear concerns only the reported crossing the observer
            // watched.
            return std::ranges::any_of(leader.at("sectorCalls"), [&](const Json &c) {
                return c.at("state") == "watching" && c.at("tick") > r->at("tick") && c.at("tick") <= now &&
                       now - c.at("tick").get<Tick>() < 30 &&
                       distance(actor_point(*r), c.at("point").get<Point>()) < 16;
            });
        });
    }
    auto counts = site_pressure(arena, reports, now);
    Json sector = leader.value("sectorCalls", Json::object()), unavailable = Json::object();
    for (auto it = sector.begin(); it != sector.end(); ++it) {
        calls.push_back(&it.value());
        auto age = now - it->at("tick").get<Tick>();
        if (it->value("duty", false) && it->at("state") == "blocked" && age >= 0 && age < 30) {
            const auto id = it.key().substr(0, it.key().find('/'));
            if (!ranked || !revised_defense(w) || std::ranges::any_of(squad, [&](auto p) {
                    const Json *duty = relief(plan, *p);
                    return p->at("id") == id && duty &&
                           it->value("goal", Json(nullptr)) == duty->at("hold") &&
                           plan.contains("defenseCall") &&
                           it->at("tick") >= plan.at("defenseCall").at("issued");
                }))
                unavailable[id] = it->at("site");
        }
    }
    sector_pressure(arena, reports, calls, now, counts);
    plan["unavailable"] = std::move(unavailable);
    for (auto it = sector.begin(); it != sector.end(); ++it)
        if (it->value("duty", false) && (it->at("state") == "moving" || it->at("state") == "arrived") &&
            now - it->at("tick").get<Tick>() < 25) {
            auto id = it.key().substr(0, it.key().find('/'));
            for (auto p : squad)
                if (p->at("id") == id) {
                    if (auto ptr = relief(plan, *p);
                        ptr && ptr->at("site") == it->at("site") &&
                        (!ranked || !revised_defense(w) ||
                         (plan.contains("defenseCall") &&
                          it->value("goal", Json(nullptr)) == ptr->at("hold") &&
                          it->at("tick") >= plan.at("defenseCall").at("issued")))) {
                        // plan is mutable here, and relief only returns references
                        // owned by plan.
                        auto &duty = const_cast<Json &>(*ptr);
                        duty["acknowledged"] = it->at("state");
                        if (it->at("state") == "moving" && !duty.contains("arriveBy"))
                            duty["arriveBy"] = it->at("tick").get<Tick>() + 30;
                    }
                }
        }
    std::map<std::string, std::vector<Tick>> losses{{"A", {}}, {"B", {}}};
    for (auto &mate : w.at("agents"))
        if (mate.at("team") == "CT" && mate.at("hp") == 0 && now - mate.at("lastHurt").get<Tick>() < 75) {
            auto pos = actor_point(mate);
            auto lost = sites.reported_site(pos);
            if (!lost && truth(plan, "opening")) {
                const auto &job = plan.at("opening").at("jobs").at(mate.at("id").get<std::string>());
                if (truth(job, "peek") && distance(pos, job.at("peek").get<Point>()) < 30)
                    lost = job.at("site").get<std::string>();
            }
            if (lost)
                losses[*lost].push_back(mate.at("lastHurt"));
        }
    for (const auto &[site, times] : losses)
        if (!times.empty() &&
            std::ranges::none_of(squad, [&](auto p) { return sites.reported_site(actor_point(*p)) == site; }))
            counts[site] += (1 + std::min<std::size_t>(2, times.size())) *
                            (1 - (now - *std::max_element(times.begin(), times.end())) / 75.);
    const Json *carrier = nullptr;
    for (auto r : reports)
        if ((!ranked || (direct_sight(*r) && r->value("confidence", 1.) >= .55)) &&
            r->value("carryingC4", false) && now - r->at("tick").get<Tick>() < 35 &&
            (!carrier || r->at("tick") > carrier->at("tick")))
            carrier = r;
    Json bomb = nullptr, on_site = nullptr;
    if (carrier) {
        bool approach;
        if (auto s = w.value("agentPolicy",0)>=12 ? site_for(arena,actor_point(*carrier),approach) : sites.reported_site(actor_point(*carrier)))
            bomb = *s;
        if (now - carrier->at("tick").get<Tick>() < 20)
            if (auto s = sites.site_at(actor_point(*carrier)))
                on_site = *s;
    }
    if (ranked) {
        compare_defense(w, cfg, arena, plan, squad, leader, reports, counts, losses, bomb, on_site);
        review_opening(arena, plan, squad, now, leader, w.value("agentPolicy",0)>=12);
        return;
    }
    std::string high = counts.at("B") > counts.at("A") ? "B" : "A", low = high == "A" ? "B" : "A";
    Json destination = on_site;
    if (destination.is_null() && counts.at(high) >= .65 && counts.at(high) - counts.at(low) >= .35)
        destination = high;
    if (destination.is_null() && leader.contains("squadPressure")) {
        const Json *newest = nullptr;
        for (auto &r : leader.at("squadPressure")) {
            auto age = now - r.at("tick").get<Tick>();
            if (age >= 0 && age < 30 && (!newest || r.at("tick") > newest->at("tick")))
                newest = &r;
        }
        if (newest)
            if (auto s = sites.reported_site(newest->at("origin").get<Point>()))
                destination = *s;
    }
    bool full = false;
    if (!destination.is_null()) {
        std::string s = destination;
        full = on_site == s || (losses.at(s).size() >= 2 && (bomb == s || counts.at(s) >= 3.5)) ||
               (counts.at(s) >= 3.5 && bomb == s);
    }
    if (full)
        plan["confirmedAttack"] = Json{{"site", destination}, {"until", now + 30}};
    else if (truth(plan, "confirmedAttack") && now < plan.at("confirmedAttack").at("until").get<Tick>()) {
        auto s = plan.at("confirmedAttack").at("site");
        auto other = s == "A" ? "B" : "A";
        if ((bomb.is_null() || bomb == s) && counts.at(other) < 1.65 &&
            (destination.is_null() || destination == s)) {
            destination = s;
            full = true;
        } else
            plan.erase("confirmedAttack");
    }
    auto assignments = [&]() {
        auto ret = Json::object();
        for (auto p : squad)
            if (auto duty = relief(plan, *p))
                ret[p->at("id").get<std::string>()] = duty->at("site");
        return ret;
    };
    auto old = assignments();
    plan["reinforce"] = !destination.is_null() && counts.at(destination.get<std::string>()) >= 1.65
                            ? destination
                            : Json(nullptr);
    if (!destination.is_null() && !truth(plan, "board"))
        brief_defense(arena, plan, squad, leader, player_profile(w, leader), now, w.at("mapId"), peer_radio(w));
    if (!on_site.is_null() && (!truth(plan, "backup") || plan.at("backup").at("site") != on_site)) {
        plan.erase("backup");
        plan.erase("secondBackup");
    }
    if (truth(plan, "backup")) {
        auto &reserve = plan.at("backup");
        std::string old_site = reserve.at("site"), opposite = old_site == "A" ? "B" : "A";
        auto conflict = std::ranges::any_of(reports, [&](const Json *r) {
            return direct_sight(*r) && now - r->at("tick").get<Tick>() < 30 &&
                   sites.reported_site(actor_point(*r)) == opposite;
        });
        auto cleared = std::ranges::any_of(calls, [&](const Json *c) {
            auto tick = c->at("tick").get<Tick>();
            return c->at("state") == "watching" && c->at("site") == old_site &&
                   reserve.value("lastEvidence", now) < tick && tick <= now &&
                   std::ranges::any_of(
                       reports,
                       [&](const Json *r) {
                           return distance(actor_point(*r), c->at("point").get<Point>()) < 22 &&
                                  r->at("tick") < tick;
                       });
        });
        if (destination == old_site)
            reserve["lastEvidence"] = now;
        else if (!on_site.is_null() || conflict || cleared)
            reserve["arriveBy"] = now - 1;
        else if (now - reserve.value("lastEvidence", reserve.value("issued", now)) < 28)
            destination = old_site;
    }
    assign_reserves(arena, plan, squad, destination, counts, now, bomb);
    if (truth(plan, "backup") && !plan.at("backup").contains("issued"))
        plan.at("backup")["issued"] = now;
    commit_reserves(arena, plan, squad, full ? destination : Json(nullptr));
    review_opening(arena, plan, squad, now, leader, w.value("agentPolicy",0)>=12);
    auto current = assignments();
    if (old == current)
        return;
    std::string label = current.empty() ? "Возврат на позиции"
                                        : (full ? "Полная перетяжка " : "Поддержка ") +
                                              current.begin().value().get<std::string>();
    Json contacts = Json::array();
    for (auto r : reports)
        if (direct_sight(*r))
            contacts.push_back(r->at("id"));
    emit(w, "rotate", label, "CT")
        .update(Json{{"player", leader.at("id")},
                     {"assignments", current},
                     {"previous", old},
                     {"contacts", contacts},
                     {"losses", Json{{"A", losses.at("A").size()}, {"B", losses.at("B").size()}}},
                     {"carrierSite", bomb}});
}
} // namespace esport
