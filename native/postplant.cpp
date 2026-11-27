#include "agent_helpers.hpp"
namespace esport {
namespace {
using Points = std::vector<Point>;
bool reserved(const Point &p, const Points &taken, double radius) {
    return std::ranges::any_of(taken, [&](auto &q) { return distance(p, q) < radius; });
}
} // namespace
Point AgentTurn::search_site(const std::string &site) {
    const auto &nav = arena.objectives().map();
    auto pos = actor_point(a), center = arena.site_point(site);
    auto cue = a.value("beepBearing", Json(nullptr));
    auto id = a.at("id").get<std::string>();
    if (!active(a, "bombSearch") || a.at("bombSearch").at("site") != site) {
        if (cue.empty() && distance(pos, center) > 25 && a.value("blockedTicks", 0) < 5)
            return center;
        a["bombSearch"] = Json{{"site", site}, {"seen", Json::array()}, {"goal", nullptr}, {"next", 0}};
    }
    auto &state = a.at("bombSearch");
    if (active(state, "goal") && distance(pos, state.at("goal").get<Point>()) > 2 &&
        (now < state.at("next").get<Tick>() || !outside_bearing(state.at("goal"), cue)) &&
        a.value("blockedTicks", 0) < 5)
        return state.at("goal");
    if (now < state.at("next").get<Tick>())
        return active(state, "goal") ? state.at("goal").get<Point>() : pos;
    state["next"] = now + 8;
    auto candidates = arena.layout().plants.at(site);
    auto seen = state.at("seen").get<std::set<AreaId>>(),
         visited = state.value("visited", std::set<AreaId>{});
    for (auto i : candidates) {
        auto &q = nav.center(i);
        if (!seen.contains(i) && distance(pos, q) < 26 && !nav.hit(pos, q, 1, 64, 5))
            seen.insert(i);
    }
    if (active(state, "goal") && distance(pos, state.at("goal").get<Point>()) <= 2 &&
        state.contains("area") && !state.at("area").is_null())
        visited.insert(state.at("area").get<AreaId>());
    Points taken;
    int sweep = state.value("sweep", 0);
    for (auto m : squad)
        if (!individual && m != &a && active(*m, "bombSearch") && m->at("bombSearch").at("site") == site && gap(*m) <= 20) {
            auto &report = m->at("bombSearch");
            if (report.value("sweep", 0) == sweep) {
                for (auto &i : report.at("seen"))
                    seen.insert(i.get<AreaId>());
                if (report.contains("visited"))
                    for (auto &i : report.at("visited"))
                        visited.insert(i.get<AreaId>());
            }
            if (active(report, "goal"))
                taken.push_back(report.at("goal").get<Point>());
        }
    std::erase_if(candidates, [&](auto i) { return seen.contains(i) || visited.contains(i); });
    if (candidates.empty()) {
        state["sweep"] = ++sweep;
        seen.clear();
        visited.clear();
        candidates = arena.layout().plants.at(site);
    }
    std::map<Point, AreaId> points;
    for (auto i : candidates) {
        auto point = nav.center(i);
        if (sweep) {
            auto &corners = arena.layout().plant_corners.at(i);
            auto &q = corners.at((slot + sweep) % corners.size());
            for (int j = 0; j < 3; ++j)
                point[j] = (point[j] + q[j]) / 2;
        }
        points[point] = i;
    }
    Points options;
    for (auto &[p, i] : points)
        options.push_back(p);
    auto rank = [&](const Point &q) {
        return std::tuple{outside_bearing(q, cue), reserved(q, taken, 7), distance(pos, q), q};
    };
    std::sort(options.begin(), options.end(), [&](auto &l, auto &r) { return rank(l) < rank(r); });
    state["seen"] = seen;
    state["visited"] = visited;
    auto goal = first_reachable(nav, pos, options, a.at("navArea").get<AreaId>());
    state["area"] = goal ? Json(points.at(*goal)) : Json(nullptr);
    state["goal"] = goal ? Json(*goal) : Json(nullptr);
    return goal.value_or(center);
}

Json AgentTurn::postplant(std::string &site, const Json &order, const Json *latest, Point &goal,
                          Point &watch) {
    const auto &nav = arena.objectives().map();
    const auto pos = actor_point(a);
    auto id = a.at("id").get<std::string>();
    if (side == "T") {
        site = device.at("site");
        auto bomb = actor_point(device);
        bool check = now - a.value("heardUse", Tick{-1000}) <= 34;
        if (std::ranges::none_of(
                squad, [&](auto p) { return p->at("id") == plan.value("deviceWatch", Json(nullptr)); })) {
            auto rank = [&](const Json *p) {
                return std::pair{distance(actor_point(*p), bomb), p->at("slot").get<int>()};
            };
            auto who = *std::min_element(squad.begin(), squad.end(),
                                         [&](auto l, auto r) { return rank(l) < rank(r); });
            plan["deviceWatch"] = who->at("id");
        }
        bool direct = check || a.at("id") == plan.at("deviceWatch");
        if (active(a, "plantCover") && a.value("watchDevice", Json(nullptr)) == direct &&
            a.value("blockedTicks", 0) < 5)
            goal = a.at("plantCover").get<Point>();
        else {
            Points taken, named;
            for (auto m : squad)
                if (m != &a && active(*m, "plantCover"))
                    taken.push_back(m->at("plantCover").get<Point>());
            for (auto &[area, q] : arena.layout().holds.at(site))
                named.push_back(q);
            auto candidates = named;
            auto sorted = nearby_points(nav, bomb, 36);
            candidates.insert(candidates.end(), sorted.begin(), sorted.end());
            std::set<Point> distinct;
            std::erase_if(candidates, [&](auto &q) { return !distinct.insert(q).second; });
            auto hold = order.at("hold").get<Point>();
            if (order.at("site") == site)
                candidates.push_back(hold);
            if (direct && !nav.hit(pos, bomb, 1, 64, 40) && distance(pos, bomb) > 5)
                candidates.push_back(pos);
            auto rank = [&](const Point &q) {
                return std::tuple{direct && bool(nav.hit(q, bomb, 1, 64, 40)), reserved(q, taken, 5),
                                  !check && std::find(named.begin(), named.end(), q) == named.end() &&
                                      q != hold,
                                  distance(q, pos)};
            };
            std::stable_sort(candidates.begin(), candidates.end(),
                             [&](auto &l, auto &r) { return rank(l) < rank(r); });
            goal = first_reachable(nav, pos, candidates).value_or(pos);
            a["plantCover"] = goal;
            a["watchDevice"] = direct;
        }
        if (a.at("watchDevice") == true)
            watch = bomb;
        else if (active(a, "plantCover") && distance(pos, goal) < 5) {
            if (!a.contains("postWatch")) {
                double best = std::numeric_limits<double>::infinity();
                auto point = watch;
                for (auto &q : arena.objectives().ingress().at(site).at(plan.at("lane").get<int>())) {
                    double d = distance(pos, q);
                    if (d > 8 && d < 90 && !nav.hit(pos, q, 1, 64, 64) && d < best) {
                        best = d;
                        point = q;
                    }
                }
                a["postWatch"] = point;
            }
            double attention = skills.at("postplant").get<double>() / 100;
            auto q = a.at("postWatch").get<Point>();
            for (int j = 0; j < 3; ++j)
                watch[j] = q[j] * attention + bomb[j] * (1 - attention);
        }
        a["status"] = check ? "Проверяет C4 после звука" : "Прикрывает C4";
        return nullptr;
    }
    site = !a.at("heardSite").is_null()      ? a.at("heardSite").get<std::string>()
           : !plan.at("reinforce").is_null() ? plan.at("reinforce").get<std::string>()
                                             : order.at("site").get<std::string>();
    if (a.at("heardSite").is_null() && device.empty() && plan.at("reinforce").is_null()) {
        if (!a.contains("inspectedSites"))
            a["inspectedSites"] = Json::object();
        auto &inspected = a.at("inspectedSites");
        if (distance(pos, arena.site_point(site)) < 15 && !inspected.contains(site))
            inspected[site] = now;
        std::string other = site == "A" ? "B" : "A";
        if (inspected.contains(site) &&
            (!inspected.contains(other) || inspected.at(site) > inspected.at(other)))
            site = other;
        if (distance(pos, arena.site_point(site)) < 15)
            inspected[site] = now;
    }
    goal = !device.empty()                ? actor_point(device)
           : !a.at("heardSite").is_null() ? search_site(site)
                                          : arena.site_point(site);
    bool helping = !action.empty() && action.at("player") != id;
    if (!device.empty() && distance(pos, goal) <= 6 && !helping && clear(a, device))
        return Json::array({"defuse", nullptr});
    if (!device.empty() && !helping && a.value("blockedTicks", 0) >= 5 &&
        a.value("useTarget", Json(nullptr)) != goal) {
        a["useTarget"] = goal;
        auto available = nav.use_position(a.at("navArea"), pos, goal, 6);
        a["useFloor"] = available ? Json(*available) : Json(nullptr);
    }
    if (!device.empty() && a.value("useTarget", Json(nullptr)) == goal && active(a, "useFloor"))
        goal = a.at("useFloor").get<Point>();
    if (helping) {
        auto who = action.at("player");
        if (a.value("coveredDefuser", Json(nullptr)) != who) {
            auto center = pos;
            Points occupied;
            for (auto m : squad) {
                if (m->at("id") == who)
                    center = actor_point(*m);
                if (m != &a && m->value("coveredDefuser", Json(nullptr)) == who && active(*m, "coverPoint"))
                    occupied.push_back(m->at("coverPoint").get<Point>());
            }
            occupied.push_back(center);
            Points choices;
            for (auto &[area, q] : arena.layout().holds.at(site))
                choices.push_back(q);
            auto rank = [&](const Point &q) {
                return std::tuple{reserved(q, occupied, 5), std::abs(q[2] - center[2]), distance(q, pos)};
            };
            std::stable_sort(choices.begin(), choices.end(),
                             [&](auto &l, auto &r) { return rank(l) < rank(r); });
            a["coveredDefuser"] = who;
            a["coverPoint"] = first_reachable(nav, pos, choices).value_or(pos);
        }
        goal = a.at("coverPoint").get<Point>();
    } else
        a.erase("coveredDefuser");
    a["status"] = helping ? "Прикрывает разминирование" : "Идёт на ретейк";
    if (!helping) {
        Json *duty = nullptr;
        if (active(plan, "retake") && plan.at("retake").at("duties").contains(id))
            duty = &plan.at("retake").at("duties").at(id);
        if (duty && !active(*duty, "done")) {
            if (now >= duty->at("latest").get<Tick>() || a.value("blockedTicks", 0) >= 5 ||
                std::ranges::none_of(squad, [&](auto m) { return m != &a && !active(*m, "saving"); }))
                (*duty)["done"] = true;
            else if (distance(pos, duty->at("stage").get<Point>()) > 4) {
                a["status"] = "Заходит на ретейк через свой проход";
                goal = duty->at("stage").get<Point>();
            } else {
                (*duty)["ready"] = true;
                bool waiting = false;
                if (active(*duty, "partner") && now < duty->value("release", now)) {
                    auto partner = duty->at("partner").get<std::string>();
                    auto &duties = plan.at("retake").at("duties");
                    waiting = duties.contains(partner) && !active(duties.at(partner), "ready") &&
                              !active(duties.at(partner), "done") && std::ranges::any_of(squad, [&](auto m) {
                                  return m != &a && m->at("id") == partner && !active(*m, "saving");
                              });
                }
                if (waiting) {
                    a["status"] = "Ждёт напарника на ретейке";
                    goal = pos;
                } else
                    (*duty)["done"] = true;
            }
        }
        watch = latest ? actor_point(*latest) : arena.site_point(site);
        if (!latest && duty && a.at("blind") <= now && distance(pos, arena.site_point(site)) <= 46) {
            if (!duty->contains("sweep"))
                (*duty)["sweep"] = Json::object();
            auto &sweep = duty->at("sweep");
            if (now < sweep.value("next", Tick{0}))
                watch = sweep.value("watch", watch);
            else {
                if (!sweep.contains("checked"))
                    sweep["checked"] = Json::array();
                auto &checked = sweep.at("checked");
                double best = 45;
                std::optional<Point> point;
                for (auto &[area, q] : arena.layout().holds.at(site)) {
                    double d = distance(pos, q);
                    if (!member_of(checked, q) && d > 5 && d < best && !nav.hit(pos, q, 1, 64, 64)) {
                        best = d;
                        point = q;
                    }
                }
                if (point) {
                    watch = *point;
                    checked.push_back(watch);
                }
                sweep["watch"] = watch;
                sweep["next"] = now + (point ? 3 + (100 - skills.at("positioning").get<int>()) / 15 : 6);
            }
        }
    } else if (!device.empty()) {
        if (latest)
            watch = actor_point(*latest);
        else {
            auto &entries =
                arena.objectives().ingress().at(site).at(order.value("lane", plan.at("lane").get<int>()));
            if (!entries.empty())
                watch = *std::min_element(entries.begin(), entries.end(), [&](auto &p, auto &q) {
                    return distance(p, goal) < distance(q, goal);
                });
        }
    }
    return nullptr;
}
} // namespace esport
