#include "radio.hpp"
#include "agent_helpers.hpp"

namespace esport {
Json AgentTurn::assist_contact(const Squad &partners, const Json &r) {
    auto &radio_memory = peer_radio(w) ? a : plan;
    const auto &nav = arena.objectives().map();
    if (partners.empty() || !visual(r) || now < r.at("tick").get<Tick>() ||
        now - r.at("tick").get<Tick>() >= 15)
        return nullptr;
    auto target = anticipated(r), origin = actor_point(a);
    double gap = distance(origin, target);
    if (gap < 16)
        return nullptr;
    auto flight = std::max(3, int(std::nearbyint(gap / 7)));
    auto land = nav.grenade(origin, target, flight).back();
    if (!radio_memory.contains("crossingCalls"))
        radio_memory["crossingCalls"] = Json::array();
    auto &calls = radio_memory.at("crossingCalls");
    bool needy =
        std::ranges::all_of(partners, [](auto m) { return active(*m, "reloadAt") || m->at("hp") < 45; });
    using Items = std::array<std::string, 3>;
    for (auto &g : needy ? Items{"Дым", "Свет", "HE"} : Items{"Свет", "HE", "Огонь"}) {
        const auto &params = cfg.at("utility").at(g);
        double radius = params[0];
        if (!member_of(a.at("utility"), g) || distance(land, target) >= radius ||
            std::ranges::any_of(calls, [&](auto &c) {
                return c.at("end") > now && c.at("item") == g && distance(c.at("point"), land) < radius;
            }))
            continue;
        if (g == "Дым") {
            if (std::ranges::any_of(squad, [&](auto m) {
                    if (m == &a || std::find(partners.begin(), partners.end(), m) != partners.end())
                        return false;
                    auto aim = observed_aim(*m);
                    return aim && near_segment(actor_point(*m), actor_point(*aim), land, radius);
                }))
                continue;
            if (side == "CT" && w.at("phase") == "live" && !screen_safe(land))
                continue;
        } else if (std::ranges::any_of(squad,
                                       [&](auto m) {
                                           auto p = actor_point(*m);
                                           return distance(p, land) < radius && !nav.hit(land, p, 1, 5, 64);
                                       }) ||
                   nav.hit(land, target, 1, 5, 64))
            continue;
        calls.push_back(Json{{"item", g}, {"point", land}, {"end", now + flight + params[1].get<int>()}});
        a["status"] = "Помогает гранатой в контакте партнёра";
        return grenade_intent(target, g);
    }
    return nullptr;
}
Json AgentTurn::retake_utility(const std::string &site) {
    auto &radio_memory = peer_radio(w) ? a : plan;
    const auto &nav = arena.objectives().map();
    if (now < std::max(a.at("throwAt").get<Tick>(), a.value("crossingReview", Tick{0})) ||
        a.at("utility").empty())
        return nullptr;
    a["crossingReview"] = now + 7;
    auto center = arena.site_point(site), origin = actor_point(a);
    Squad mates;
    for (auto m : squad)
        if (m != &a && !active(*m, "saving") && distance(actor_point(*m), center) < 55)
            mates.push_back(m);
    if (mates.empty() || distance(origin, center) > 83)
        return nullptr;
    std::vector<Point> reports, cover;
    for (auto &r : a.at("knowledge"))
        if (now - r.at("tick").get<Tick>() < 35 && visual(r) && distance(actor_point(r), center) < 55)
            reports.push_back(actor_point(r));
    for (auto &[area, q] : arena.layout().holds.at(site)) {
        auto d = distance(q, center);
        if (d > 9 && d < 45)
            cover.push_back(q);
    }
    if (!radio_memory.contains("crossingCalls"))
        radio_memory["crossingCalls"] = Json::array();
    auto &calls = radio_memory.at("crossingCalls");
    calls.erase(std::remove_if(calls.begin(), calls.end(), [&](auto &c) { return c.at("end") <= now; }),
                calls.end());
    auto nearest = [&](const Point &q) {
        double d = std::numeric_limits<double>::infinity();
        for (auto m : mates)
            d = std::min(d, distance(q, actor_point(*m)));
        return d;
    };
    std::stable_sort(cover.begin(), cover.end(), [&](auto &l, auto &r) { return nearest(l) < nearest(r); });
    auto candidates = reports;
    candidates.insert(candidates.end(), cover.begin(), cover.end());
    auto inventory = a.at("utility").get<std::set<std::string>>();
    std::vector<std::string> items(inventory.begin(), inventory.end());
    auto level = [&](const std::string &g) {
        return skills.at(cfg.at("grenadeSkills").at(g).get<std::string>()).get<int>();
    };
    std::stable_sort(items.begin(), items.end(), [&](auto &l, auto &r) { return level(l) > level(r); });
    static const std::map<std::string, std::string> purpose{{"Свет", "Поддерживает вход"},
                                                            {"Дым", "Изолирует позицию"},
                                                            {"Огонь", "Проверяет укрытие"},
                                                            {"HE", "Проверяет контакт"}};
    for (auto &item : items) {
        if (!purpose.contains(item) || (item == "HE" && reports.empty()))
            continue;
        double radius = cfg.at("utility").at(item)[0];
        for (auto &q : candidates) {
            double d = distance(q, origin);
            if (d <= 12 || d >= 75 ||
                std::ranges::any_of(calls, [&](auto &c) { return distance(q, c.at("point")) < radius; }))
                continue;
            bool screen = item == "Дым" || item == "Огонь";
            if ((screen && distance(q, center) < radius + 6) || (item == "Свет" && nearest(q) >= radius + 30))
                continue;
            if (std::ranges::any_of(squad, [&](auto m) {
                    auto p = actor_point(*m);
                    return distance(q, p) < radius + 3 && !nav.hit(q, p, 1, 5, 64);
                }))
                continue;
            auto track = nav.grenade(origin, q, std::max(3, int(std::nearbyint(d / 7))));
            if (distance(track.back(), q) > 6)
                continue;
            if (screen && active(plan, "retake") &&
                std::ranges::any_of(plan.at("retake").at("duties"),
                                    [&](auto &duty) { return distance(q, duty.at("entry")) < radius; }))
                continue;
            calls.push_back(Json{
                {"item", item},
                {"point", q},
                {"end", now + static_cast<Tick>(track.size()) + cfg.at("utility").at(item)[1].get<int>()}});
            return grenade_intent(q, item, purpose.at(item));
        }
    }
    return nullptr;
}

Json AgentTurn::plant_intercept(Point &goal, Point &watch, Json &cue) {
    auto &radio_memory = peer_radio(w) ? a : plan;
    const auto &nav = arena.objectives().map();
    const auto pos = actor_point(a);
    const std::string site = cue.at("site");
    if (a.at("blind") <= now && !active(a, "reloadAt") && now >= a.at("ready") && a.at("ammo") > 1 &&
        cue.value("checkingShots", 0) < 3) {
        const Json *reported = nullptr;
        for (auto &r : a.at("knowledge"))
            if (active(r, "carryingC4") && visual(r) && r.at("tick") <= now &&
                now - r.at("tick").get<Tick>() <= 24 && (!reported || r.at("tick") > reported->at("tick")))
                reported = &r;
        if (reported) {
            auto p = anticipated(*reported);
            if (!outside_bearing(p, cue.at("bearing")) && arena.objectives().site_at(p) == site &&
                std::ranges::none_of(
                    squad, [&](auto m) { return m != &a && near_segment(pos, p, actor_point(*m), 3); }) &&
                combat.sensors().shot_transmission(
                    pos, p, cfg.at("weapons").at(a.at("weapon").get<std::string>()).at("penetration"))) {
                cue["checkingShots"] = cue.value("checkingShots", 0) + 1;
                heading_to(a, p);
                a["status"] = "Проверяет последнее донесение о C4";
                return Json::array({"shoot", coordinate(p)});
            }
        }
    }
    Tick end = cue.at("tick").get<Tick>() + cfg.at("rules").at("plant").get<int>();
    std::vector<Point> points;
    for (auto &q : arena.objectives().samples(site))
        if (!outside_bearing(q, cue.at("bearing")))
            points.push_back(q);
    if (!cue.contains("peek")) {
        std::vector<Point> taken;
        for (auto m : squad)
            if (!individual && m != &a && active(*m, "plantCue")) {
                const auto &c = m->at("plantCue");
                if (active(c, "peek") && now - c.at("tick").template get<Tick>() < 30)
                    taken.push_back(c.at("watch"));
            }
        double reach = std::max(0., (end - now) * 1.65);
        auto spots = nearby_points(nav, pos, std::min(24., reach));
        spots.insert(spots.begin(), pos);
        using Choice = std::tuple<int, int, double, Point, Point>;
        std::vector<Choice> picks;
        for (auto &spot : spots) {
            std::vector<Point> seen;
            for (auto &q : points)
                if (!nav.hit(spot, q, 1, 64, 40, true))
                    seen.push_back(q);
            if (seen.empty())
                continue;
            auto rank = [&](auto &aim) {
                int count = 0, independent = 0;
                auto dx = aim[0] - spot[0], dy = aim[1] - spot[1];
                for (auto &q : seen) {
                    auto x = q[0] - spot[0], y = q[1] - spot[1];
                    if (dx * x + dy * y < .5 * std::hypot(dx, dy) * std::hypot(x, y))
                        continue;
                    ++count;
                    independent += std::ranges::all_of(taken, [&](auto &r) { return distance(q, r) > 6; });
                }
                return std::tuple{independent, count, -distance(spot, aim)};
            };
            auto aim = *std::max_element(seen.begin(), seen.end(),
                                         [&](auto &l, auto &r) { return rank(l) < rank(r); });
            auto [ind, count, d] = rank(aim);
            picks.emplace_back(-ind, -count, distance(pos, spot), spot, aim);
        }
        std::sort(picks.begin(), picks.end());
        cue["peek"] = nullptr;
        cue["watch"] = nullptr;
        for (auto &[ind, count, gap, spot, aim] : picks) {
            if (spot != pos) {
                auto to = nav.locate(spot);
                if (!to)
                    continue;
                auto path = nav.path(a.at("navArea"), pos, *to, spot, {});
                if (!path)
                    continue;
                Point old = pos;
                double total = 0;
                for (auto &[x, y, z, id] : *path) {
                    Point p{x, y, z};
                    total += distance(old, p);
                    old = p;
                }
                if (total > reach)
                    continue;
            }
            cue["peek"] = spot;
            cue["watch"] = aim;
            break;
        }
    }
    if (!active(cue, "peek"))
        return nullptr;
    goal = cue.at("peek").get<Point>();
    watch = cue.at("watch").get<Point>();
    if (!active(cue, "denialChecked") && now >= a.at("throwAt")) {
        cue["denialChecked"] = true;
        if (!points.empty()) {
            auto key = [&](auto &q) {
                double total = 0;
                for (auto &p : points)
                    total += distance(q, p);
                return std::pair{total, q};
            };
            auto target = *std::min_element(points.begin(), points.end(),
                                            [&](auto &l, auto &r) { return key(l) < key(r); });
            int flight = std::max(3, int(std::nearbyint(distance(pos, target) / 7)));
            if (now + flight < end)
                for (std::string item : {"HE", "Огонь"}) {
                    double radius = cfg.at("utility").at(item)[0];
                    if (!member_of(a.at("utility"), item) || std::ranges::any_of(squad, [&](auto m) {
                            return distance(actor_point(*m), target) < radius;
                        }))
                        continue;
                    if (radio_memory.contains("crossingCalls") &&
                        std::ranges::any_of(radio_memory.at("crossingCalls"), [&](auto &c) {
                            return c.at("item") == item && now < c.at("end") &&
                                   distance(c.at("point"), target) < radius;
                        }))
                        continue;
                    if (distance(nav.grenade(pos, target, flight).back(), target) < radius / 2) {
                        radio_memory["crossingCalls"].push_back(
                            Json{{"item", item},
                                 {"point", target},
                                 {"end", now + flight + cfg.at("utility").at(item)[1].get<int>()}});
                        a["status"] = "Срывает установку по звуку";
                        return grenade_intent(target, item);
                    }
                    break;
                }
        }
    }
    a["status"] = "Проверяет звук установки";
    return nullptr;
}
} // namespace esport
