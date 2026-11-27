#include "agent_helpers.hpp"
#include "grenades.hpp"
#include "radio.hpp"

namespace esport {
Json AgentTurn::spatial_intent() {
    const auto &nav = arena.objectives().map();
    auto &slots = plan.at("orders").at("slots");
    auto &home = slots.at(slot);
    const auto pos = actor_point(a);
    bool live = w.at("phase") == "live", holding = live && side == "CT";
    Point sector_watch{};
    auto &assigned = holding ? attention(sector_watch) : home;
    // Publishing a call can grow the ordered plan object and relocate its child nodes.
    const Json order = assigned;
    const bool anchor = side == "CT" && (order == slots[0] || order == slots[1]);
    std::string site = plan.at("site");
    Json last_report;
    const Json *latest = nullptr;
    auto rank = [&](const Json &r) {
        return std::pair{r.at("id") == a.at("tradeTarget") && now <= a.at("tradeUntil"),
                         r.at("tick").get<Tick>()};
    };
    for (auto &r : a.at("knowledge"))
        if (now - r.at("tick").get<Tick>() < 35 && (!latest || rank(r) > rank(*latest))) {
            last_report = r;
            latest = &last_report;
        }
    auto goal = order.at("hold").get<Point>(), watch = order.at("watch").get<Point>();
    int familiar = player.at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0);
    auto remaining = w.at("deadline").get<Tick>() - now;
    bool carrying = !device.empty() && device.at("carrier") == a.at("id");
    if (!live) {
        auto result = postplant(site, order, latest, goal, watch);
        if (!result.is_null())
            return result;
    } else if (side == "T") {
        if (!device.empty() && !active(device, "carrier") && !recovery.empty() &&
            recovery.at("player") == a.at("id")) {
            goal = recovery.at("point").get<Point>();
            a["status"] = "Подбирает C4";
        } else {
            if (carrying) {
                auto at = arena.objectives().site_at(pos);
                if (at && (*at == site || remaining < 90))
                    return prepare_plant(*at);
            }
            const auto &route = order.at("via");
            auto index = a.at("waypoint").get<std::size_t>();
            const bool arrived = index < route.size() && distance(pos, route[index]) < 2.6;
            if (arrived)
                a["waypoint"] = ++index;
            if (index < route.size() && remaining > 145)
                goal = route[index].get<Point>();
            else if (carrying)
                goal = order.at("plant").get<Point>();
            a["status"] = "Выход на " + site;
            if (index && index < route.size() &&
                (plan.at("style") == "Сбор" || plan.at("style") == "Групповой выход" ||
                 plan.at("style") == "Контроль карты")) {
                if (small_groups(w) && !carrying && remaining > 180 && !active(plan, "board")) {
                    auto paired = stage_pair(goal, arrived);
                    if (!paired.is_null())
                        return paired;
                }
                const auto &lane = order.contains("lane") ? order.at("lane") : route;
                int cohesion = 0;
                double nearest = std::numeric_limits<double>::infinity();
                bool behind = false, blocked = false;
                for (auto m : squad)
                    if (m != &a) {
                        const auto &job = slots.at(m->at("slot").get<int>());
                        if ((job.contains("lane") ? job.at("lane") : job.at("via")) != lane)
                            continue;
                        cohesion = std::max(cohesion, chemistry(w, a, *m));
                        nearest = std::min(nearest, gap(*m));
                        if (peer_radio(w)) {
                            const auto key = m->at("id").get<std::string>() + "/order";
                            if (a.contains("peerCalls") && a.at("peerCalls").contains(key)) {
                                const auto &update = a.at("peerCalls").at(key);
                                if (now - update.at("tick").get<Tick>() < 30) {
                                    behind |= update.value("waypoint", 0) < index;
                                    blocked |= update.at("state") == "unavailable";
                                }
                            }
                        } else {
                            behind |= m->at("waypoint") < index;
                            blocked |= m->value("blockedTicks", 0) >= 5;
                        }
                    }
                double spacing =
                    52 -
                    (skills.at("synchronization").get<int>() + skills.at("timing").get<int>() +
                     player.at("roleMastery").value(a.at("playingRole").get<std::string>(), 0) + cohesion) /
                        16.;
                if (behind && !blocked && nearest > spacing &&
                    arena.objectives().site_cost(site, a.at("navArea"), 0) / (nav.unit() * 1.65) +
                            cfg.at("rules").at("plant").get<int>() + 45 <
                        remaining) {
                    goal = pos;
                    a["status"] = "Ждёт партнёра для выхода";
                }
            }
        }
    } else {
        site = order.at("site");
        watch = sector_watch;
        if (relief(plan, a)) {
            a["status"] = "Перетягивается на " + site;
            if (auto q = flank(assigned, home)) {
                goal = *q;
                a["status"] = "Обходит к " + site + " по другому входу";
            }
        } else if (home.contains("screen") && &assigned == &home.at("screen"))
            a["status"] = "Проверяет передовую позицию";
        else
            a["status"] = "Занимает " + site;
    }
    bool checking = holding && active(a, "plantCue") && a.at("plantCue").at("tick") <= now &&
                    now - a.at("plantCue").at("tick").get<Tick>() < 30;
    if (!checking && action.empty()) {
        Json result;
        if (live)
            result = crossing(order, site);
        else if (side == "CT" && (active(a, "heardSite") || active(plan, "retake")) &&
                 remaining > cfg.at("rules").at(a.at("kit") == true ? "kitDefuse" : "defuse").get<int>() + 25)
            result = retake_utility(site);
        if (!result.is_null())
            return result;
    }
    if (checking) {
        auto result = plant_intercept(goal, watch, a.at("plantCue"));
        if (!result.is_null())
            return result;
    }
    std::string other = site == "A" ? "B" : "A";
    auto false_lane = [&]() {
        std::vector<Point> candidates;
        for (auto &q : arena.objectives().ingress().at(other).at(plan.at("lane").get<int>())) {
            auto d = distance(pos, q);
            if (d > 12 && d < 48)
                candidates.push_back(q);
        }
        return candidates;
    };
    if (side == "T" && live && active(plan, "probe") && !plan.at("probe").contains("stations") && !latest &&
        action.empty() && active(device, "carrier")) {
        auto &probe = plan.at("probe");
        if (!active(probe, "released") && !active(plan, "rotated") && squad.size() >= 4 &&
            now < probe.at("until")) {
            if (a.at("id") == probe.at("scout")) {
                watch = arena.site_point(other);
                if (distance(pos, probe.at("goal")) > 5) {
                    goal = probe.at("goal").get<Point>();
                    a["status"] = "Проверяет второй подход";
                } else {
                    if (!probe.contains("reportDue"))
                        probe["reportDue"] = now + 1 + (100 - skills.at("communication").get<int>()) / 12;
                    goal = pos;
                    a["status"] = "Наблюдает второй подход";
                }
            } else {
                auto d = arena.objectives().site_cost(site, a.at("navArea"),
                                                      std::numeric_limits<double>::infinity()) /
                         nav.unit();
                if (d > 20 && d < 50 &&
                    a.at("status").get_ref<const std::string &>().starts_with("Выход на ")) {
                    a["status"] = "Ждёт сведений со второго подхода";
                    goal = pos;
                    watch = arena.site_point(site);
                }
            }
        }
        if (a.at("status") == "Наблюдает второй подход" && member_of(a.at("utility"), "Ложная") &&
            now >= a.at("throwAt")) {
            auto points = false_lane();
            if (!points.empty())
                return grenade_intent(points.front(), "Ложная");
        }
    }
    if (side == "T" && !active(plan, "probe") && plan.at("style") == "Контроль карты" &&
        a.at("playingRole") == "lurker" && live && a.at("waypoint") == 0 && !latest &&
        now - plan.at("start").get<Tick>() < 2 * familiar && !carrying) {
        auto &ids = arena.layout().places.at(arena.profile().at("middle").get<std::string>());
        auto nearest = *std::min_element(ids.begin(), ids.end(), [&](auto l, auto r) {
            return distance(pos, nav.center(l)) < distance(pos, nav.center(r));
        });
        goal = nav.center(nearest);
        a["status"] = "Проверяет центр";
        if (member_of(a.at("utility"), "Ложная") && now >= a.at("throwAt") && distance(pos, goal) <= 22) {
            auto points = false_lane();
            if (!points.empty()) {
                auto aim = *std::min_element(points.begin(), points.end(), [&](auto &l, auto &r) {
                    return distance(l, goal) < distance(r, goal);
                });
                a["status"] = "Отвлекает на другом подходе";
                return grenade_intent(aim, "Ложная");
            }
        }
    }
    Tick age = latest ? now - latest->at("tick").get<Tick>() : 0;
    int pursuit = latest && latest->at("source") == "Слух"
                      ? int((8 + (100 - skills.at("patience").get<int>()) / 3) *
                            (coordinated_utility(w) ? latest->value("confidence", 1.) : 1.))
                      : 12 + skills.at("aggression").get<int>() / 2;
    if (latest && live && (side == "CT" || !carrying) && action.empty() && age <= pursuit) {
        auto contact = actor_point(*latest);
        auto d = distance(pos, contact);
        if (anchor && latest->at("source") != "Слух" && !a.at("utility").empty() && now >= a.at("throwAt") &&
            age < 18 && d > 20 && d < 80) {
            for (auto &q :
                 arena.objectives().ingress().at(site).at(order.value("lane", plan.at("lane").get<int>()))) {
                if (distance(q, contact) > 12 || nav.hit(pos, q, 1, 64, 64) ||
                    std::ranges::any_of(squad, [&](auto m) { return distance(actor_point(*m), q) < 21; }))
                    continue;
                std::string item = member_of(a.at("utility"), "Огонь") ? "Огонь"
                                   : member_of(a.at("utility"), "Дым") ? "Дым"
                                                                       : "";
                if (item == "Дым" && (smokes_plant(site, q) || !screen_safe(q)))
                    continue;
                if (!item.empty()) {
                    a["status"] = "Сдерживает выход на плент";
                    return grenade_intent(q, item);
                }
            }
        }
        bool check =
            !checking && !relief(plan, a) &&
            (!holding || (visual(*latest) && age < 20 && distance(pos, goal) < 14 &&
                          std::ranges::any_of(
                              squad, [&](auto m) { return m != &a && m->at("hp") != 0 && gap(*m) < 40; })));
        if (check && !anchor && distance(goal, contact) < 55 - skills.at("discipline").get<int>() / 4. &&
            d > 6) {
            if (!nav.hit(pos, contact, 1, 64, 64))
                goal = pos;
            else {
                Json key = Json::array({latest->at("id"), latest->at("tick")});
                if (a.value("checkContact", Json(nullptr)) != key || a.value("blockedTicks", 0) >= 5) {
                    auto choices = nearby_points(nav, contact, 24);
                    auto cost = [&](auto &q) {
                        return distance(pos, q) + std::abs(15 - distance(q, contact));
                    };
                    std::stable_sort(choices.begin(), choices.end(),
                                     [&](auto &l, auto &r) { return cost(l) < cost(r); });
                    std::erase_if(choices, [&](auto &q) { return bool(nav.hit(q, contact, 1, 64, 64)); });
                    auto peek = first_reachable(nav, pos, choices);
                    a["checkContact"] = key;
                    a["checkPosition"] = peek ? Json(*peek) : Json(nullptr);
                }
                if (active(a, "checkPosition"))
                    goal = a.at("checkPosition").get<Point>();
            }
            a["status"] = "Проверяет сообщение о контакте";
        }
    }
    if (latest && action.empty() && !checking && !a.at("utility").empty() &&
        now >= std::max(a.at("throwAt").get<Tick>(), a.value("assistReview", Tick{0})) && age < 15 &&
        (a.at("playingRole") == "support" || skills.at("coordination").get<int>() + familiar >= 145)) {
        Squad partners;
        for (auto m : squad)
            if (m != &a && ally_covers(*m, *latest))
                partners.push_back(m);
        if (!partners.empty()) {
            a["assistReview"] = now + 5;
            auto result = assist_contact(partners, *latest);
            if (!result.is_null())
                return result;
        }
    }
    if (side == "T" && live && a.at("status").get_ref<const std::string &>().starts_with("Выход на ")) {
        auto original = goal;
        if (active(a, "revisedApproach")) {
            auto &r = a.at("revisedApproach");
            if (r.at("from") == goal && r.at("site") == site)
                goal = r.at("to").get<Point>();
        }
        if (a.value("blockedTicks", 0) >= 8 && a.value("blockedGoal", Json(nullptr)) == goal) {
            std::vector<Point> plants;
            for (auto id : arena.layout().plants.at(site))
                plants.push_back(nav.center(id));
            auto points = carrying ? plants : nearby_points(nav, goal, 22);
            std::stable_sort(points.begin(), points.end(),
                             [&](auto &l, auto &r) { return distance(l, goal) < distance(r, goal); });
            if (!carrying)
                points.insert(points.end(), plants.begin(), plants.end());
            auto q = first_reachable(nav, pos, points, a.at("navArea").get<AreaId>());
            if (q && *q != goal) {
                a["revisedApproach"] = Json{{"site", site}, {"from", original}, {"to", *q}};
                auto index = a.at("waypoint").get<std::size_t>();
                if (index < order.at("via").size() && order.at("via")[index] == goal)
                    a["waypoint"] = index + 1;
                goal = *q;
            }
        }
    }
    bool moved = move(goal, plan.at("style") == "Быстро" || !live ? 2 : 1.65);
    bool follow =
        latest &&
        (!holding || (!checking && (latest->at("source") == "Зрение" ||
                                    (distance(pos, actor_point(*latest)) < 55 &&
                                     (latest->at("source") == "Слух" || latest->at("source") == "Радио")) ||
                                    std::ranges::any_of(squad, [&](auto m) {
                                        return m != &a && ally_covers(*m, *latest) &&
                                               distance(pos, actor_point(*m)) < 35;
                                    }))));
    if (moved) {
        if (side == "CT" && (holding || !latest) && distance(actor_point(a), goal) < 22 + familiar / 6.)
            heading_to(a, watch);
        if (follow && age < 12 + skills.at("positioning").get<int>() / 5)
            heading_to(a, anticipated(*latest));
        return Json::array({"move", nullptr});
    }
    if (follow && age <= pursuit && latest->at("tick") >= a.value("heardUse", Tick{-1000}))
        watch = anticipated(*latest);
    a["heading"] = heading_gap(actor_point(a), watch) +
                   (.6 - skills.at("discipline").get<int>() / 260.) * std::sin((now + 13 * slot) / 26.);
    return Json::array({"hold", nullptr});
}
} // namespace esport
