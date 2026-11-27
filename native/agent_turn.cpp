#include "grenades.hpp"
#include "radio.hpp"
#include "agent_helpers.hpp"
#include "economy.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>
namespace esport {
namespace {
bool has(const Json &set, const Json &value) { return std::find(set.begin(), set.end(), value) != set.end(); }
bool direct(const Json &sight) { return sight.at("source") == "Зрение" || sight.at("source") == "Радио"; }
Json in_hand(const Json &gun) {
    return Json{{"weapon", gun.at("weapon")}, {"ammo", gun.at("ammo")}, {"reserve", gun.at("reserve")}};
}
} // namespace

Json rescue_c4(Json &w, const PhysicalNavigation &nav, const Squad &allies) {
    auto &bomb = w.at("bomb");
    if (!bomb.at("carrier").empty() || !bomb.at("site").empty()) {
        bomb.erase("recovery");
        return nullptr;
    }
    auto goal = actor_point(bomb);
    if (bomb.contains("recovery") && !bomb.at("recovery").empty()) {
        auto &current = bomb.at("recovery");
        if (current.at("drop") == goal && std::ranges::any_of(allies, [&](const Json *p) {
                return p->at("id") == current.at("player") && p->value("blockedTicks", 0) < 20;
            }))
            return current;
    }
    std::optional<std::tuple<double, int, std::string, Point>> best;
    for (auto a : allies) {
        Point pos = actor_point(*a);
        auto point = nav.use_position(a->at("navArea"), pos, goal, 7);
        if (!point)
            continue;
        auto area = nav.locate(*point);
        if (!area)
            continue;
        auto path = nav.path(a->at("navArea"), pos, *area, *point, {});
        if (!path)
            continue;
        double length = 0;
        for (auto &[x, y, z, to] : *path) {
            Point q{x, y, z};
            length += distance(pos, q);
            pos = q;
        }
        auto option = std::tuple{length, a->at("slot").get<int>(), a->at("id").get<std::string>(), *point};
        if (!best || option < *best)
            best = option;
    }
    if (!best)
        return nullptr;
    bomb["recovery"] = Json{{"player", std::get<2>(*best)}, {"drop", goal}, {"point", std::get<3>(*best)}};
    return bomb.at("recovery");
}

AgentTurn::AgentTurn(Json &world, Json &actor, const Squad &allies, const Json &config, const OpeningMap &map,
                     const Combat &arms, const Json &rescue)
    : side(actor.at("team")), now(world.at("tick")), slot(actor.at("slot")), w(world), a(actor),
      squad(allies), individual(world.contains("agentPolicy")), cfg(config), arena(map), grid(map.objectives().grid()), combat(arms), recovery(rescue),
      player(player_profile(w, a)), skills(player.at("skills")), plan(w.at("plans").at(side)),
      previous(actor.at("status")), step_index(actor.value("stepIndex", 0)),
      prior_position(actor_point(actor)) {}
bool AgentTurn::clear(const Json &l, const Json &r) const {
    if (grid)
        return grid->clear(xy(l), xy(r));
    return !arena.objectives().map().hit(actor_point(l), actor_point(r), 1, l.contains("hp") ? 64 : 5,
                                         r.contains("hp") ? 64 : 5);
}
bool AgentTurn::move(const Point &point, double pace) {
    const auto &nav = arena.objectives().map();
    if (!w.at("effects").empty() && spatial_grenades(w) && a.at("visible").empty() &&
        w.at("deadline").get<Tick>() - now > 65 && !active(a, "groupDuty") && !active(a, "groupLead") &&
        !active(a, "saving")) {
        const Point pos = actor_point(a);
        for (const auto &cloud : w.at("effects")) {
            if (cloud.at("kind") != "Дым" || !cloud.contains("lobes"))
                continue;
            const int wait = cloud.at("end").get<int>() - now;
            if (wait > 0 && wait < 7 + (100 - skills.at("risk").get<int>()) / 3 && gap(cloud) <= 32 &&
                clear(a, cloud) && !crosses_volume(cloud, pos, pos) && crosses_volume(cloud, pos, point)) {
                a["status"] = "Ждёт рассеивания дыма";
                return false;
            }
        }
    }
    return travel(a, player, nav, point, pace, fire, now);
}
Json AgentTurn::movement(const Point &goal, double pace) {
    return Json::array({move(goal, pace) ? "move" : "hold", nullptr});
}
void AgentTurn::pickup() {
    auto &ground = w.at("groundWeapons");
    if (ground.empty() || a.at("blind") > now)
        return;
    Json primary = nullptr, secondary = nullptr;
    for (const auto *item : {&a, &a.at("holster")})
        if (!item->empty()) {
            auto name = item->at("weapon");
            (has(cfg.at("sidearms"), name) ? secondary : primary) = name;
        }
    for (auto it = ground.begin(); it != ground.end(); ++it) {
        std::string name = it->at("weapon");
        bool pistol = has(cfg.at("sidearms"), name);
        if (pistol && !secondary.is_null() &&
            cfg.at("weapons").at(secondary.get<std::string>()).at("price") >=
                cfg.at("weapons").at(name).at("price"))
            continue;
        if ((!pistol && !primary.is_null()) || (it->at("ammo") == 0 && it->at("reserve") == 0) ||
            gap(*it) > 6 || !clear(a, *it))
            continue;
        auto gun = *it;
        ground.erase(it);
        if (pistol && !secondary.is_null()) {
            Json prior = {{"id", gun.at("id")}, {"x", a.at("x")}, {"y", a.at("y")}};
            if (!grid)
                prior["z"] = a.at("z");
            prior.update(in_hand(a.at("weapon") == secondary ? a : a.at("holster")));
            ground.push_back(std::move(prior));
        }
        equip_weapon(a, in_hand(gun), cfg);
        emit(w, "weapon_pickup", a.at("name").get<std::string>() + " подобрал " + name, side)
            .update(Json{{"player", a.at("id")}, {"weapon", name}, {"dropId", gun.at("id")}});
        return;
    }
}
void AgentTurn::prepare() {
    pickup();
    auto &bomb = w.at("bomb");
    device = side == "T" ? bomb : a.value("seenDevice", Json(nullptr));
    int delay = 1 + (100 - skills.at("communication").get<int>()) / 12;
    if (side == "CT" && !bomb.at("site").empty() && gap(bomb) < 72) {
        if (a.at("heardSite").empty()) {
            a["heardSite"] = bomb.at("site");
            w.at("messages")
                .push_back(Json{
                    {"team", side}, {"sender", a.at("id")}, {"site", bomb.at("site")}, {"due", now + delay}});
        }
        if (!grid && now % 10 == 0) {
            auto [dx, dy] = sound_direction(actor_point(a), actor_point(bomb));
            a["beepBearing"] = Json::array({a.at("x"), a.at("y"), dx, dy});
        }
        auto sees_device = [&] {
            if (gap(bomb) >= 30 || !clear(a, bomb))
                return false;
            if (grid && !individual)
                return true;
            if (a.at("blind") > now || (individual && !in_range_fov(a, actor_point(bomb))))
                return false;
            return std::ranges::none_of(w.at("effects"), [&](const Json &f) {
                return f.at("kind") == "Дым" && f.at("land") <= now && now < f.at("end") &&
                       crosses_volume(f, actor_point(a), actor_point(bomb));
            });
        };
        if (grid && sees_device())
            device = bomb;
        if (!grid && device.is_null() && sees_device()) {
            device = Json::object();
            for (auto k : {"x", "y", "z", "site", "carrier"})
                device[k] = bomb.at(k);
            a["seenDevice"] = device;
            w.at("messages")
                .push_back(
                    Json{{"team", side}, {"sender", a.at("id")}, {"device", device}, {"due", now + delay}});
        }
    }
    if (side == "T" && bomb.at("carrier").empty() && bomb.at("site").empty() && gap(bomb) <= 7 &&
        (grid || clear(a, bomb))) {
        bomb["carrier"] = a.at("id");
        device = bomb;
        emit(w, "pickup", a.at("name").get<std::string>() + " поднял C4", "T")["player"] = a.at("id");
    }
    for (const auto &f : w.at("effects")) {
        if (f.at("kind") != "Огонь" || f.at("land") > now || gap(f) >= 70)
            continue;
        if (coordinated_utility(w) && f.contains("lobes")) {
            // A player can see fire entering a doorway while its origin stays
            // behind a wall.
            const auto pos = actor_point(a);
            for (const auto &cell : f.at("lobes")) {
                const double radius = cell.at("reach");
                if (radius <= 0)
                    continue;
                const Point p = cell.at("p");
                if (distance(pos, p) > radius &&
                    (a.at("blind") > now || !in_range_fov(a, p) ||
                     (grid ? !grid->clear(xy(a), {p[0], p[1]})
                           : arena.objectives().map().hit(pos, p, 1, 64, 5).has_value())))
                    continue;
                fire.emplace_back(p, radius);
                if (grid)
                    grid_fire.push_back({{"x", p[0]}, {"y", p[1]}, {"radius", radius}});
            }
        } else if (clear(a, f) && (!spatial_grenades(w) || a.at("blind") <= now)) {
            append_volume(f, fire);
            if (grid) {
                if (!f.contains("lobes"))
                    grid_fire.push_back(f);
                else
                    for (const auto &c : f.at("lobes"))
                        if (c.at("reach") > 0)
                            grid_fire.push_back(
                                {{"x", c.at("p")[0]}, {"y", c.at("p")[1]}, {"radius", c.at("reach")}});
            }
        }
    }
    if (!w.at("action").empty())
        for (const auto &p : w.at("agents"))
            if (p.at("team") == side && p.at("id") == w.at("action").at("player"))
                action = w.at("action");
    if (side == "CT" && w.at("phase") == "live" && plan.contains("opening") && !plan.at("opening").empty()) {
        auto &job = plan.at("opening").at("jobs").at(a.at("id").get<std::string>());
        if (job.contains("peek") && distance(actor_point(a), job.at("peek").get<Point>()) < 6) {
            auto look = job.at("watch").get<Point>();
            opening_sight = (!spatial_grenades(w) || a.at("blind") <= now) &&
                            !arena.objectives().map().hit(actor_point(a), look, 1, 64, 5) &&
                            std::ranges::none_of(w.at("effects"), [&](const Json &f) {
                                return f.at("kind") == "Дым" && f.at("land") <= now && now < f.at("end") &&
                                       crosses_volume(f, actor_point(a), look);
                            });
        }
    }
}
void AgentTurn::check_incoming(const std::string &intent) {
    auto cue = a.value("incoming", Json(nullptr)), shared = a.value("pressureCall", Json(nullptr));
    if (!shared.empty() && (cue.empty() || now - cue.at("tick").get<Tick>() > 12))
        cue = shared;
    if (cue.empty() || (intent != "move" && intent != "hold") || !a.at("visible").empty() ||
        a.at("blind") > now)
        return;
    auto age = now - cue.at("tick").get<Tick>();
    if (age <= 0 || age > 12)
        return;
    auto dir = cue.at("bearing").get<std::array<double, 4>>();
    auto angle = std::atan2(dir[3], dir[2]);
    const Json *latest = nullptr;
    for (auto &r : a.at("knowledge")) {
        auto t = now - r.at("tick").get<Tick>();
        auto p = actor_point(r);
        double x = p[0] - dir[0], y = p[1] - dir[1];
        if (direct(r) && t >= 0 && t < 20 && x * dir[2] + y * dir[3] >= std::abs(x * dir[3] - y * dir[2]) &&
            (!latest || r.at("tick") > latest->at("tick")))
            latest = &r;
    }
    if (latest) {
        auto target = std::atan2(latest->at("y").get<double>() - a.at("y").get<double>(),
                                 latest->at("x").get<double>() - a.at("x").get<double>());
        auto confidence =
            (1 - (now - latest->at("tick").get<Tick>()) / 20.) * skills.at("game_reading").get<int>() / 100;
        double diff = std::fmod(target - angle + std::numbers::pi, 2 * std::numbers::pi);
        if (diff < 0)
            diff += 2 * std::numbers::pi;
        angle += (diff - std::numbers::pi) * confidence;
    }
    a["heading"] = angle;
}
void AgentTurn::duty_feedback() {
    auto duty = relief(plan, a);
    auto job = plan.value("opening", Json::object())
                   .value("jobs", Json::object())
                   .value(a.at("id").get<std::string>(), Json::object());
    const auto &order = duty ? *duty : plan.at("orders").at("slots").at(slot);
    auto goal = duty ? duty->at("hold") : job.value("peek", order.at("hold"));
    std::string state;
    if (a.value("blockedTicks", 0) >= 5 ||
        (!duty && job.contains("withdrawn") && job.at("withdrawn") != 0 && job.at("withdrawn") != false))
        state = "blocked";
    else if (!duty && job.contains("partner") && !job.at("partner").empty() &&
             std::ranges::none_of(squad, [&](auto m) { return m->at("id") == job.at("partner"); }))
        state = "unsupported";
    else if (!a.at("visible").empty() && (duty || a.at("visible").size() > 1 || a.at("hp") < 65))
        state = "engaged";
    else if (distance(actor_point(a), goal.get<Point>()) < 8)
        state = duty ? "arrived" : "ready";
    else if (duty)
        state = "moving";
    else
        return;
    auto stamp = Json::array({order.at("site"), goal, state});
    auto prior = a.value("lastDutyFeedback", Json(nullptr));
    if (!prior.empty() && prior.at("stamp") == stamp && now - prior.at("tick").get<Tick>() < 35)
        return;
    a["lastDutyFeedback"] = Json{{"stamp", stamp}, {"tick", now}};
    Json call = {{"feedback", true},
                 {"state", state},
                 {"point", actor_point(a)},
                 {"site", order.at("site")},
                 {"lane", order.value("lane", 0)},
                 {"tick", now},
                 {"duty", bool(duty)}};
    a["sectorCalls"][a.at("id").get<std::string>() + "/order"] = call;
    w.at("messages")
        .push_back(Json{{"team", "CT"},
                        {"sender", a.at("id")},
                        {"crossing", call},
                        {"due", now + 1 + (100 - skills.at("communication").get<int>()) / 12}});
}
void AgentTurn::finish(const Json &intent) {
    const auto kind = intent.at(0).get<std::string>();
    if (!grid) {
        if (side == "T" && kind == "throw" && intent.at(1).value("purpose", std::string{}) == "Ложный выход")
            a["feintThrown"] = true;
        if (a.at("status") != "Отворачивается от флешки")
            check_incoming(kind);
        if (a.value("lastBlockedTick", Tick{-1}) != now)
            a["blockedTicks"] = 0;
        if (side == "T" && w.at("phase") == "live" && a.value("blockedTicks", 0) >= 20 &&
            now - a.value("lastRouteReport", Tick{-100}) >= 60) {
            auto site = plan.at("site");
            const auto id = a.at("id").get<std::string>();
            if (plan.contains("commandJobs") && plan.at("commandJobs").contains(id))
                site = plan.at("commandJobs").at(id).at("site");
            a["lastRouteReport"] = now;
            a["routeReports"][a.at("id").get<std::string>()] = Json::array({site, now});
            w.at("messages")
                .push_back(Json{{"team", side},
                                {"sender", a.at("id")},
                                {"blockedSite", site},
                                {"due", now + 1 + (100 - skills.at("communication").get<int>()) / 12}});
            if (w.value("agentPolicy", 0) >= 9)
                w.at("messages").back()["observed"] = now;
        }
        if (side == "CT" && w.at("phase") == "live" && now % 5 == slot)
            duty_feedback();
    }
    if (peer_radio(w))
        peer_feedback(kind);
    if (kind == "move") {
        if (!grid && (individual || (side == "T" && w.at("phase") == "live")) && now % 5 == slot &&
            distance(prior_position, actor_point(a)) > .9)
            combat.hear(w, a, "Шаги", 88);
        a["lastMove"] = now;
        a["movingTicks"] = a.at("movingTicks").get<int>() + 1;
    }
    if (plan.contains("board") && !plan.at("board").empty()) {
        std::string status = a.at("status"), text = a.at("name").get<std::string>() + " · " + status;
        if (a.at("stepIndex") != step_index &&
            (!a.contains("lastRefusal") || a.at("lastRefusal").at("tick") != now))
            emit(w, "board_step", text, side).update(Json{{"player", a.at("id")}, {"step", step_index}});
        else if (previous != status &&
                 (status == "К капитану после потери союзника" || status == "Пережидает огонь за укрытием" ||
                  status == "Обходит огонь" || status == "Подбирает C4"))
            emit(w, "adapt", text, side)["player"] = a.at("id");
    }
    if (a.at("reloadAt") ==
        now + cfg.at("weapons").at(a.at("weapon").get<std::string>()).at("reload").get<int>())
        emit(w, "reload",
             a.at("name").get<std::string>() + " перезаряжает " + a.at("weapon").get<std::string>(), side)
            .update(Json{{"weapon", a.at("weapon")}, {"player", a.at("id")}});
}
} // namespace esport
