#include "grenades.hpp"
#include "radio.hpp"
#include "agent_helpers.hpp"
#include <limits>
namespace esport {
bool AgentTurn::smokes_plant(const std::string &site, const Point &point) const {
    const auto &nav = arena.objectives().map();
    for (auto id : arena.layout().plants.at(site)) {
        const auto &p = nav.center(id);
        if (distance(point, p) <= cfg.at("utility").at("Дым")[0].get<double>() &&
            !nav.hit(point, p, 1, 48, 48))
            return true;
    }
    return false;
}
Json AgentTurn::crossing(const Json &order, std::string site) {
    auto &radio_memory = peer_radio(w) ? a : plan;
    const auto &nav = arena.objectives().map();
    if (a.at("utility").empty() || now < a.at("throwAt").get<Tick>() ||
        now < a.value("crossingReview", Tick{0}))
        return nullptr;
    a["crossingReview"] = now + 14;
    auto pos = actor_point(a);
    Json probe = active(plan, "probe") ? plan.at("probe") : Json::object();
    bool feint = side == "T" && !active(probe, "released") && plan.at("rotated") == false &&
                 a.at("id") == probe.value("scout", Json(nullptr));
    if (collective_attack(w) && probe.contains("stations"))
        feint &= probe.value("feint", false) && !a.value("feintThrown", false);
    if (side == "T" && plan.contains("commandKind")) {
        feint = plan.at("commandKind") == "feint" && plan.at("commandJobs").contains(a.at("id").get<std::string>()) &&
                !a.value("feintThrown", false);
    }
    if (feint && !probe.contains("stations") && !plan.contains("commandKind"))
        site = site == "A" ? "B" : "A";
    if (!radio_memory.contains("crossingCalls"))
        radio_memory["crossingCalls"] = Json::array();
    auto &calls = radio_memory.at("crossingCalls");
    calls.erase(std::remove_if(calls.begin(), calls.end(),
                               [&](const Json &r) { return now >= r.at("end").get<Tick>(); }),
                calls.end());
    bool defending = side == "CT" && w.at("phase") == "live", pressure = false, flash_support = false;
    Squad pushing;
    std::vector<Point> targets;
    std::vector<std::string> gadgets;
    auto add_named = [&](const Json &name) {
        auto areas = arena.layout().places.at(name.get<std::string>());
        std::sort(areas.begin(), areas.end());
        for (auto id : areas)
            targets.push_back(nav.center(id));
    };
    if (defending) {
        if (order.value("maneuver", std::string{}) == "save")
            return nullptr;
        int lane = plan.at("lane");
        if (order.at("site") == site)
            lane = order.value("lane", lane);
        targets = arena.objectives().ingress().at(site).at(lane);
        add_named(arena.profile().at(site).at(lane).back());
        Reports reports;
        for (auto &r : a.at("knowledge"))
            if (now - r.at("tick").get<Tick>() < 35) {
                auto p = actor_point(r);
                if (arena.objectives().reported_site(p) == site ||
                    std::ranges::any_of(targets, [&](auto &q) { return distance(p, q) < 16; }))
                    reports.push_back(&r);
            }
        if (a.at("id") == plan.value("utilityReserve", std::string{}) && a.at("utility").size() == 1 &&
            std::ranges::none_of(reports, [](auto r) { return visual(*r); }) &&
            w.at("deadline").get<Tick>() - now > 160)
            return nullptr;
        pressure = !reports.empty();
        if (pressure) {
            auto gap = [&](const Point &p) {
                double best = std::numeric_limits<double>::infinity();
                for (auto r : reports)
                    best = std::min(best, distance(p, actor_point(*r)));
                return best;
            };
            std::stable_sort(targets.begin(), targets.end(),
                             [&](auto &l, auto &r) { return gap(l) < gap(r); });
        }
        for (auto m : squad)
            if (m != &a) {
                auto &home = plan.at("orders").at("slots").at(m->at("slot").get<int>());
                if (active(home, "screen") && (small_groups(w) ? !relief(plan, *m) : &assignment(plan, *m, squad) == &home.at("screen")) &&
                    distance(actor_point(*m), home.at("screen").at("hold").get<Point>()) < 28 && gap(*m) < 40)
                    pushing.push_back(m);
            }
        flash_support = !pushing.empty() && member_of(a.at("utility"), "Свет") &&
                        !active(radio_memory.value("pushFlash", Json::object()), site) &&
                        skills.at("flashes").get<int>() + skills.at("coordination").get<int>() >= 100;
        if (!pressure && !flash_support) {
            const auto &costs = arena.contest(site, lane).first;
            double best = std::numeric_limits<double>::infinity();
            for (auto id : arena.layout().attack_spawns)
                if (auto it = costs.find(id); it != costs.end())
                    best = std::min(best, it->second);
            double arrival = best / (2 * nav.unit());
            auto elapsed = now - plan.at("start").get<Tick>();
            if (!radio_memory.contains("openingThrows"))
                radio_memory["openingThrows"] = Json::object();
            if (active(plan, "opening") || radio_memory.at("openingThrows").contains(site) ||
                active(a, "screenedOpening") || elapsed > arrival + 55 || elapsed + 35 < arrival ||
                ((plan.at("buy") == "Эко" || plan.at("buy") == "Частичная") && a.at("utility").size() == 1))
                return nullptr;
        }
        if (flash_support)
            std::erase_if(targets, [&](auto &q) {
                return std::ranges::none_of(pushing, [&](auto m) {
                    double d = distance(actor_point(*m), q);
                    return d > 16 && d < 60;
                });
            });
        gadgets = flash_support ? std::vector<std::string>{"Свет"} : std::vector<std::string>{"Огонь", "Дым"};
        if (relief(plan, a) && pressure)
            gadgets = {"Дым", "Свет", "Огонь"};
    } else {
        if (collective_attack(w) && feint) {
            const auto &entries = arena.objectives().ingress().at(site).at(order.value("lane", 0));
            targets.insert(targets.end(), entries.begin(), entries.end());
            add_named(arena.profile().at(site).at(order.value("lane", 0)).back());
        }
        for (auto &label : arena.profile().at("guards").at(site))
            add_named(label);
        if (collective_attack(w) && !feint) {
            for (const auto &r : a.at("knowledge")) {
                if (!visual(r) || now - r.at("tick").get<Tick>() >= 25)
                    continue;
                const Point sight = actor_point(r);
                if (distance(sight, arena.site_point(site)) < 45) {
                    pressure = true;
                    targets.push_back(sight);
                }
            }
        }
        gadgets = feint ? std::vector<std::string>{"Ложная", "Дым", "Свет"}
                        : std::vector<std::string>{"Дым", "Свет"};
        if (collective_attack(w) && pressure)
            gadgets = {"Огонь", "Дым", "Свет"};
        if (collective_attack(w) && !pressure && !feint && active(probe, "stations") &&
            !active(probe, "released") && a.at("utility").size() == 1)
            return nullptr;
        if (!feint && std::ranges::none_of(squad, [&](auto m) { return m != &a && gap(*m) < 35; }))
            return nullptr;
    }
    std::erase_if(targets, [&](auto &p) {
        double d = distance(pos, p);
        return d <= 24 || d >= 68;
    });
    if (!defending || !pressure)
        std::stable_sort(targets.begin(), targets.end(),
                         [&](auto &l, auto &r) { return distance(pos, l) < distance(pos, r); });
    if (targets.size() > std::size_t(defending ? 16 : 8))
        targets.resize(defending ? 16 : 8);
    for (auto &p : targets) {
        std::string item;
        for (auto &g : gadgets) {
            if (!member_of(a.at("utility"), g))
                continue;
            if (coordinated_utility(w) && g == "Свет") {
                if (flash_reserved(p))
                    continue;
                // A lane approach needs a threatened angle or a teammate actually
                // approaching it.
                if (!pressure && !flash_support && !feint && std::ranges::none_of(squad, [&](auto m) {
                        return m != &a && now - m->value("lastMove", Tick{-100}) <= 3 &&
                               distance(actor_point(*m), p) < distance(pos, p) && sees_teammate(*m) &&
                               in_range_fov(*m, p);
                    }))
                    continue;
            }
            double radius = cfg.at("utility").at(g)[0];
            // plan may acquire additional keys above. Reacquire the list from its owner.
            if (std::ranges::any_of(radio_memory.at("crossingCalls"), [&](const Json &c) {
                    return c.at("item") == g && distance(c.at("point").get<Point>(), p) < radius;
                }))
                continue;
            if (std::ranges::any_of(squad, [&](auto m) {
                    if (g == "Свет" && spatial_grenades(w))
                        return flash_risk(*m, p, std::max(3, int(distance(pos, p) / 7)));
                    return distance(actor_point(*m), p) < (g == "Свет" ? radius : 18);
                }))
                continue;
            item = g;
            break;
        }
        if (item.empty())
            continue;
        int flight = std::max(3, int(std::nearbyint(distance(pos, p) / 7)));
        auto land = nav.grenade(pos, p, flight).back();
        if (distance(land, p) > 8 ||
            (defending && item == "Дым" && (smokes_plant(site, land) || !screen_safe(land))))
            continue;
        radio_memory.at("crossingCalls")
            .push_back(Json{{"item", item},
                            {"point", p},
                            {"end", now + flight + cfg.at("utility").at(item)[1].get<int>()}});
        if (defending && !pressure) {
            a["screenedOpening"] = true;
            radio_memory[flash_support ? "pushFlash" : "openingThrows"][site] = a.at("id");
        }
        a["status"] = feint ? "Имитирует выход" : "Готовит гранату на подход";
        std::string purpose;
        if (collective_attack(w) && !defending)
            purpose = feint ? "Ложный выход" : pressure ? "Изолирует контакт" : "Выход на плент";
        if (defending)
            purpose = relief(plan, a)                        ? "Прикрывает перетяжку"
                      : (!pushing.empty() && item == "Свет") ? "Поддерживает поджим"
                      : pressure                             ? "Сдерживает выход"
                                                             : "Стартовый контроль";
        auto intent = grenade_intent(p, item, purpose);
        if (peer_radio(w) && defending && !pressure) {
            intent[1]["openingCall"] = flash_support ? "flash" : "screen";
            intent[1]["site"] = site;
        }
        return intent;
    }
    return nullptr;
}
Json AgentTurn::hold_sector() {
    const auto &nav = arena.objectives().map();
    if (!active(plan, "probe") || !plan.at("probe").contains("stations") ||
        active(plan.at("probe"), "released") || plan.at("rotated") == true)
        return nullptr;
    auto &probe = plan.at("probe");
    auto id = a.at("id").get<std::string>();
    auto &st = probe.at("stations").at(id);
    auto pos = actor_point(a), goal = st.at("point").get<Point>();
    std::string label = st.at("label");
    a["status"] = "Берёт контроль · " + label;
    int delay = 1 + (100 - skills.at("communication").get<int>()) / 12;
    if (distance(pos, goal) > 4) {
        if (collective_attack(w) && probe.value("feint", false) && probe.at("scout") == id &&
            !a.value("feintThrown", false) && distance(pos, goal) < 35) {
            auto cast = crossing(plan.at("orders").at("slots").at(slot), st.at("sector"));
            if (!cast.is_null())
                return cast;
        }
        if (move(goal, 1.65))
            return Json::array({"move", nullptr});
        if (collective_attack(w) && a.value("blockedTicks", 0) >= 8)
            signal_group("sector", "blocked", goal, st.at("sector"));
        if (a.value("blockedTicks", 0) >= 20 &&
            (!probe.contains("unreachable") || !probe.at("unreachable").contains(id)))
            probe["unreachable"][id] = now + delay;
        return Json::array({"hold", nullptr});
    }
    auto watch = st.at("watch").get<Point>();
    std::string site = st.value("sector", plan.at("site").get<std::string>());
    heading_to(a, watch);
    a["status"] = "Наблюдает · " + label;
    if (!probe.at("reports").contains(id)) {
        if (!st.contains("check")) {
            Point flank = watch;
            double best = -1;
            for (auto &q : arena.objectives().ingress().at(site).at(plan.at("lane").get<int>())) {
                auto d = distance(pos, q), wide = distance(q, watch);
                if (d > 6 && d < 75 && !nav.hit(pos, q, 1, 64, 64) && wide > best) {
                    best = wide;
                    flank = q;
                }
            }
            bool covered = std::ranges::any_of(squad, [&](const Json *m) {
                return m != &a && gap(*m) < 28 && (!small_groups(w) || sees_teammate(*m)) && !nav.hit(actor_point(*m), flank, 1, 64, 64) &&
                       std::cos(m->at("heading").get<double>() - heading_gap(actor_point(*m), flank)) >= .5;
            });
            st["check"] = covered ? watch : flank;
        }
        heading_to(a, st.at("check"));
        probe.at("reports")[id] = now + delay + (100 - skills.at("execution").get<int>()) / 25;
    }
    if (st.contains("check") && now < probe.at("reports").at(id).get<Tick>())
        heading_to(a, st.at("check"));
    if (collective_attack(w) && now >= probe.at("reports").at(id).get<Tick>())
        signal_group("sector", "held", goal, site);
    auto result = crossing(plan.at("orders").at("slots").at(slot), site);
    return result.is_null() ? Json::array({"hold", nullptr}) : result;
}
Json AgentTurn::prepare_plant(const std::string &site) {
    const auto &nav = arena.objectives().map();
    if (!action.empty() || w.at("deadline").get<Tick>() - now <= cfg.at("rules").at("plant").get<int>() + 10)
        return Json::array({"plant", site});
    auto pos = actor_point(a);
    if (collective_attack(w) && !active(plan, "board")) {
        if (!a.contains("plantSpot") || a.at("plantSpot").at("site") != site) {
            Reports angles;
            for (const auto &r : a.at("knowledge"))
                if (visual(r) && now - r.at("tick").get<Tick>() < 40 &&
                    !nav.hit(pos, actor_point(r), 1, 46, 64))
                    angles.push_back(&r);
            Point best = pos;
            auto exposure = [&](const Point &p) {
                return std::count_if(angles.begin(), angles.end(), [&](auto r) {
                    return !nav.hit(p, actor_point(*r), 1, 46, 64);
                });
            };
            auto risk = angles.size();
            if (risk) {
                for (const auto &p : arena.objectives().samples(site)) {
                    if (distance(pos, p) > 10)
                        continue;
                    auto score = exposure(p);
                    if (score > risk || (score == risk && distance(pos, p) >= distance(pos, best)))
                        continue;
                    auto dest = nav.locate(p);
                    auto route = dest ? nav.path(a.at("navArea"), pos, *dest, p, {}) : std::nullopt;
                    if (route && walk_length(pos, *route) <= 13) {
                        best = p;
                        risk = score;
                    }
                }
            }
            a["plantSpot"] = {{"site", site}, {"point", best}, {"until", now + 12}};
        }
        const auto point = a.at("plantSpot").at("point").get<Point>();
        if (now < a.at("plantSpot").at("until") && distance(pos, point) > 2 && move(point, 1.65)) {
            a["status"] = "Занимает место установки";
            return Json::array({"move", nullptr});
        }
    }
    if (!active(a, "plantCheck") || a.at("plantCheck").at("site") != site ||
        distance(pos, a.at("plantCheck").at("origin").get<Point>()) > 6) {
        Reports reports;
        for (auto &r : a.at("knowledge"))
            if (r.at("source") != "Слух" && r.at("source") != "Граната" &&
                now - r.at("tick").get<Tick>() < 50 && !nav.hit(pos, actor_point(r), 1, 64, 64))
                reports.push_back(&r);
        std::stable_sort(reports.begin(), reports.end(),
                         [](auto l, auto r) { return l->at("tick") > r->at("tick"); });
        std::vector<Point> angles, choices;
        for (auto r : reports)
            angles.push_back(actor_point(*r));
        for (auto &[id, q] : arena.layout().holds.at(site))
            choices.push_back(q);
        std::stable_sort(choices.begin(), choices.end(),
                         [&](auto &l, auto &r) { return distance(pos, l) < distance(pos, r); });
        for (auto &p : choices) {
            if (angles.size() >= 3)
                break;
            auto d = distance(pos, p);
            if (d > 8 && d < 65 &&
                std::ranges::all_of(
                    angles, [&](auto &q) { return distance(p, q) > 12; }) &&
                !nav.hit(pos, p, 1, 64, 64))
                angles.push_back(p);
        }
        a["plantCheck"] = Json{{"site", site}, {"origin", pos}, {"angles", angles}, {"index", 0}};
    }
    auto &check = a.at("plantCheck");
    while (check.at("index").get<std::size_t>() < check.at("angles").size()) {
        auto index = check.at("index").get<std::size_t>();
        auto q = check.at("angles").at(index).get<Point>();
        bool covered = std::ranges::any_of(squad, [&](const Json *m) {
            if (m == &a || (small_groups(w) ? !sees_teammate(*m) :
                            m->at("ammo") == 0 || m->at("blind") > now || m->at("reloadAt") != 0))
                return false;
            auto p = actor_point(*m);
            double dx = q[0] - p[0], dy = q[1] - p[1], h = m->at("heading");
            return dx * std::cos(h) + dy * std::sin(h) >= .75 * std::hypot(dx, dy) && distance(p, pos) < 55 &&
                   !nav.hit(p, q, 1, 64, 64);
        });
        if (!covered) {
            a["status"] = "Проверяет угол перед установкой";
            heading_to(a, q);
            if (!check.contains("until"))
                check["until"] = now + 2 + (100 - skills.at("positioning").get<int>()) / 15;
            if (now < check.at("until").get<Tick>())
                return Json::array({"hold", nullptr});
        }
        check.erase("until");
        check["index"] = index + 1;
    }
    return Json::array({"plant", site});
}
} // namespace esport
