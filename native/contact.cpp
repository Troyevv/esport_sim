#include "grenades.hpp"
#include "agent_turn.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>

namespace esport {
namespace {
bool has(const Json &xs, const Json &v) { return std::find(xs.begin(), xs.end(), v) != xs.end(); }
bool can_see(const Json &a, const Json &target) {
    auto p = actor_point(a), q = actor_point(target);
    double dx = q[0] - p[0], dy = q[1] - p[1], h = a.at("heading"), dot = dx * std::cos(h) + dy * std::sin(h);
    return dot >= 0 && 4 * dot * dot >= dx * dx + dy * dy;
}
} // namespace
bool AgentTurn::sees_teammate(const Json &mate) const {
    if (a.at("blind") > now || gap(mate) > 45 || !can_see(a, mate) || !clear(a, mate))
        return false;
    const auto start = actor_point(a), end = actor_point(mate);
    return std::ranges::none_of(w.at("effects"), [&](const Json &f) {
        return f.at("kind") == "Дым" && f.at("land") <= now && now < f.at("end") &&
               crosses_volume(f, start, end);
    });
}
// Estimate a visible ally's line of fire against *our own* reports. A teammate's
// untransmitted sighting, target ID and crosshair are private.
const Json *AgentTurn::observed_aim(const Json &mate) const {
    if (!individual) {
        const auto &id = mate.at("target");
        if (!id.is_string() || !mate.at("knowledge").contains(id.get_ref<const std::string &>()))
            return nullptr;
        return &mate.at("knowledge").at(id.get_ref<const std::string &>());
    }
    if (a.at("knowledge").empty() || !sees_teammate(mate))
        return nullptr;
    const auto end = actor_point(mate);
    const Json *best = nullptr;
    double alignment = .94; // A narrow sector around the visible weapon direction.
    const double heading = mate.at("heading");
    for (const auto &r : a.at("knowledge")) {
        if (!r.contains("id") || (r.at("source") != "Зрение" && r.at("source") != "Радио") ||
            r.at("tick") > now || now - r.at("tick").get<Tick>() > 14)
            continue;
        auto point = actor_point(r);
        double dx = point[0] - end[0], dy = point[1] - end[1];
        double dot = (dx * std::cos(heading) + dy * std::sin(heading)) / std::max(1., std::hypot(dx, dy));
        if (dot > alignment) {
            alignment = dot;
            best = &r;
        }
    }
    return best;
}
bool AgentTurn::ally_covers(const Json &mate, const Json &report) const {
    if (!individual)
        return mate.at("target") == report.at("id");
    auto aim = observed_aim(mate);
    return aim && aim->at("id") == report.at("id");
}
Json AgentTurn::select_contact() const {
    const auto &visible = a.at("visible");
    if (visible.empty())
        return nullptr;
    const auto &intel = a.at("knowledge");
    if (visible.size() == 1)
        return intel.at(visible[0].get<std::string>());
    std::set<std::string> focus;
    for (auto m : squad)
        if (m != &a && gap(*m) < 25 && clear(a, *m)) {
            if (individual) {
                if (auto aim = observed_aim(*m))
                    focus.insert(aim->at("id"));
            } else if (m->at("target").is_string())
                focus.insert(m->at("target"));
        }
    auto priority = [&](const Json &id) {
        const auto &sight = intel.at(id.get<std::string>());
        auto p = actor_point(a), q = actor_point(sight);
        double x = p[0] - q[0], y = p[1] - q[1], apparent = distance(p, q);
        if (sight.contains("bodySector") && sight.contains("weapon") && sight.at("weapon").is_string() &&
            cfg.at("weapons").contains(sight.at("weapon").get<std::string>())) {
            auto h = sight.at("bodySector").get<double>() * std::numbers::pi / 4;
            auto align = (x * std::cos(h) + y * std::sin(h)) / std::max(1., std::hypot(x, y));
            auto &gun = cfg.at("weapons").at(sight.at("weapon").get<std::string>());
            apparent /=
                1 + (1 + align) / 2 *
                        (gun.at("damage").get<double>() / std::max(1, gun.at("interval").get<int>())) *
                        skills.at("game_reading").get<int>() / 1000;
        }
        if (focus.contains(id.get<std::string>()))
            apparent -= skills.at("coordination").get<int>() / 4.;
        return std::pair{!sight.contains("interaction") || sight.at("interaction").empty() ||
                             sight.at("interaction") == false,
                         apparent};
    };
    return intel.at(std::min_element(visible.begin(), visible.end(), [&](auto &l, auto &r) {
                        return priority(l) < priority(r);
                    })->get<std::string>());
}
void AgentTurn::service_weapon() {
    auto spare = a.at("holster");
    if (a.at("ammo") == 0 && a.at("reserve") == 0 && !spare.empty() &&
        (spare.at("ammo") != 0 || spare.at("reserve") != 0)) {
        Json old = {{"weapon", a.at("weapon")}, {"ammo", a.at("ammo")}, {"reserve", a.at("reserve")}};
        a.update(spare);
        a["holster"] = std::move(old);
        a["reloadAt"] = 0;
    }
    const auto &spec = cfg.at("weapons").at(a.at("weapon").get<std::string>());
    if (a.at("reloadAt") != 0 && now >= a.at("reloadAt").get<Tick>()) {
        int count = std::min(spec.at("mag").get<int>() - a.at("ammo").get<int>(), a.at("reserve").get<int>());
        a["ammo"] = a.at("ammo").get<int>() + count;
        a["reserve"] = a.at("reserve").get<int>() - count;
        a["reloadAt"] = 0;
    }
    if (a.at("ammo") == 0 && a.at("reserve") != 0 && a.at("reloadAt") == 0)
        a["reloadAt"] = now + spec.at("reload").get<int>();
}
bool AgentTurn::screen_safe(const Point &point) const {
    const double radius = cfg.at("utility").at("Дым")[0];
    for (auto m : squad) {
        auto &order = assignment(plan, *m, squad);
        auto hold = order.at("hold").get<Point>(), watch = order.at("watch").get<Point>();
        if (distance(hold, point) < radius ||
            (near_segment(hold, watch, point, radius) && distance(point, watch) > radius))
            return false;
        if (m != &a && (individual || !m->at("visible").empty()))
            if (auto aim = observed_aim(*m); aim && near_segment(actor_point(*m), actor_point(*aim), point, radius))
                return false;
    }
    return true;
}
Json AgentTurn::seek_cover(const Json &contact, bool requested) {
    const auto &nav = arena.objectives().map();
    bool exposed = false;
    if (!requested && !contact.empty() && a.at("visible").size() > 1) {
        int engaged = 0;
        bool backup = false;
        for (auto m : squad)
            if (m != &a && gap(*m) < 45) {
                engaged += has(a.at("visible"), m->at("target"));
                backup |= m->at("ammo") != 0 && m->at("reloadAt") == 0 && can_see(*m, contact) &&
                          !nav.hit(actor_point(*m), actor_point(contact), 1, 64, 64);
            }
        exposed = int(a.at("visible").size()) > 1 + engaged && !backup &&
                  skills.at("positioning").get<int>() + skills.at("discipline").get<int>() >
                      skills.at("aggression").get<int>() + skills.at("risk").get<int>();
    }
    if (!contact.empty() &&
        (requested || a.at("reloadAt") != 0 || exposed || (a.at("hp") < 35 && a.at("visible").size() > 1)) &&
        now >= a.value("coverReview", Tick{0})) {
        auto threat = actor_point(contact), pos = actor_point(a);
        std::set<Point> spots;
        for (auto &[id, q] : nav.centers())
            if (distance(q, pos) < 15)
                spots.insert(q);
        for (auto &q : arena.layout().cover)
            if (distance(q, pos) <= 15)
                spots.insert(q);
        std::vector<Point> choices;
        for (auto &q : spots)
            if (distance(q, pos) > 1 && nav.hit(q, threat, 1, 64, 64))
                choices.push_back(q);
        auto rank = [&](const Point &q) {
            double near = std::numeric_limits<double>::infinity();
            for (auto m : squad)
                if (m != &a)
                    near = std::min(near, distance(q, actor_point(*m)));
            return std::tuple{near < 3, exposed && near >= 35, distance(q, pos), q};
        };
        std::sort(choices.begin(), choices.end(), [&](auto &p, auto &q) { return rank(p) < rank(q); });
        a["coverReview"] = now + 5 + (100 - skills.at("positioning").get<int>()) / 12;
        for (auto &q : choices) {
            auto zone = nav.locate(q);
            if (!zone)
                continue;
            auto path = nav.path(a.at("navArea"), pos, *zone, q, {});
            if (!path)
                continue;
            auto prev = pos;
            double length = 0;
            for (auto &[x, y, z, to] : *path) {
                Point p{x, y, z};
                length += distance(prev, p);
                prev = p;
            }
            if (length > 20)
                continue;
            a["shelter"] = q;
            if (a.value("flashLevel", 0.) < .5 && side == "CT" && has(a.at("utility"), "Дым") &&
                now >= a.at("throwAt").get<Tick>() && distance(pos, threat) > 24 &&
                std::ranges::none_of(squad, [&](auto m) { return m != &a && ally_covers(*m, contact); })) {
                Point screen;
                for (int i = 0; i < 3; ++i)
                    screen[i] = pos[i] + (threat[i] - pos[i]) * .55;
                auto landing =
                    nav.grenade(pos, screen, std::max(3, int(std::nearbyint(distance(pos, screen) / 7))))
                        .back();
                if (distance(landing, screen) < 6 && screen_safe(landing)) {
                    a["coverUntil"] = std::max(a.at("reloadAt").get<Tick>(), now + 14);
                    return Json::array({"throw", Json{{"x", screen[0]},
                                                      {"y", screen[1]},
                                                      {"z", screen[2]},
                                                      {"utility", "Дым"},
                                                      {"purpose", "Прикрывает отход"}}});
                }
            }
            a["coverUntil"] = std::max(a.at("reloadAt").get<Tick>(), now + 10);
            break;
        }
    }
    if (a.contains("shelter") && !a.at("shelter").empty() && now < a.value("coverUntil", Tick{0})) {
        a["status"] = "Уходит за укрытие";
        bool moved = move(a.at("shelter").get<Point>(), 2);
        if (!moved && a.value("blockedTicks", 0)) {
            a.erase("shelter");
            return nullptr;
        }
        return Json::array({moved ? "move" : "hold", nullptr});
    }
    return nullptr;
}
Json AgentTurn::duel(const Json &contact) {
    auto pos = actor_point(a), target = actor_point(contact);
    auto old = a.at("heading").get<double>(), heading = std::atan2(target[1] - pos[1], target[0] - pos[0]);
    a["heading"] = heading;
    if (a.at("target") != contact.at("id")) {
        double angle = std::fmod(heading - old + std::numbers::pi, 2 * std::numbers::pi);
        if (angle < 0)
            angle += 2 * std::numbers::pi;
        angle -= std::numbers::pi;
        auto s = [&](std::string key) { return skills.at(key).get<int>(); };
        double delay =
            1 + (100 - s("reaction")) / 23. + std::abs(angle) / std::numbers::pi * (100 - s("flick")) / 11;
        auto &prev = a.at("previousTarget");
        if (!prev.is_null() && prev != contact.at("id"))
            delay += (100 - s("target_switch")) / 20.;
        if (now - a.at("lastMove").get<Tick>() <= 2)
            delay += (100 - s("peeking")) / 25.;
        if (side == "T" && a.at("playingRole") == "entry" && prev.is_null())
            delay += (100 - s("entry")) / 30.;
        if (contact.at("id") == a.at("tradeTarget") && now <= a.at("tradeUntil").get<Tick>())
            delay -= s("trades") / 35.;
        if (squad.size() == 1)
            delay += (100 - s("clutch")) / 24.;
        if (a.contains("mind")) delay -= a.at("mind").at("focus").get<int>() / 10.;
        delay += a.value("flashLevel", 0.) * (9. - s("reaction") / 20.);
        a["target"] = contact.at("id");
        a["previousTarget"] = contact.at("id");
        a["ready"] =
            std::max(a.at("ready").get<Tick>(), now + std::max<Tick>(1, Tick(std::nearbyint(delay))));
    }
    a["observedSpeed"] = contact.value("speed", Json(0));
    a["status"] = a.at("reloadAt") != 0 ? "Перезаряжается" : "Держит контакт";
    double gap = distance(pos, target);
    const bool prefer_utility=a.contains("coachOrder") && a.at("coachOrder").at("kind")=="utility";
    if (!a.at("utility").empty() && now >= a.at("throwAt").get<Tick>() && gap > 18) {
        auto &spec = cfg.at("weapons").at(a.at("weapon").get<std::string>());
        if (grid) {
            const auto item = a.at("utility")[0].get<std::string>();
            double decisions = skills.at("decisions"),
                   radius = cfg.at("utility").at(item)[0].get<double>() * decisions / 100;
            bool unsafe = (item == "HE" || item == "Огонь" || item == "Свет") &&
                          std::ranges::any_of(squad, [&](auto m) {
                              return item == "Свет" && spatial_grenades(w)
                                         ? flash_risk(*m, target, 3)
                                         : gap2(xy(*m), xy(contact)) < radius;
                          });
            bool soon = a.at("ammo") != 0 && a.at("reloadAt") == 0 && a.at("ready") < now + 5;
            if (!unsafe &&
                !(soon && !prefer_utility && gap <= 18 + decisions * std::min(.6, spec.at("damage").get<double>() / 75)))
                return Json::array({"throw", contact});
        } else {
            const auto &nav = arena.objectives().map();
            int flight = std::max(3, int(std::nearbyint(gap / 7)));
            bool backup = std::ranges::any_of(
                     squad, [&](auto m) { return m != &a && ally_covers(*m, contact); }),
                 vulnerable = a.at("reloadAt") != 0 || a.at("hp") < 45;
            auto ready =
                std::max<Tick>(0, std::max(a.at("ready").get<Tick>(), a.at("reloadAt").get<Tick>()) - now);
            const bool coordination = coordinated_utility(w);
            const Tick warn =
                coordination ? std::max(0, 2 + (100 - skills.at("communication").get<int>()) / 12 - flight)
                             : 0;
            int shots = std::min(
                a.at("ammo").get<int>(),
                int(std::max(0., 1 + std::floor(double(cfg.at("throwRecovery").get<int>() - 1 - ready) /
                                                spec.at("interval").get<int>()))));
            auto chance = weapon_accuracy(w, cfg, a, spec, gap, a.at("burst")) / 100.;
            double damage = spec.at("damage"), opportunity = shots * damage * chance * (prefer_utility ? .8 : 1.);
            std::set<std::string> seen;
            std::optional<std::pair<double, std::string>> best;
            for (auto &g : a.at("utility")) {
                std::string item = g;
                if (item == "Ложная" || !seen.insert(item).second)
                    continue;
                double radius = cfg.at("utility").at(item)[0], benefit = 0;
                bool friends = std::ranges::any_of(squad, [&](auto m) {
                    if (item == "Свет" && spatial_grenades(w))
                        return flash_risk(*m, target, flight);
                    return distance(target, actor_point(*m)) < radius &&
                           !nav.hit(target, actor_point(*m), 1, 5, 64);
                });
                if (item == "Дым") {
                    if (!vulnerable || backup ||
                        (w.at("phase") == "live" && side == "CT" && !screen_safe(target)))
                        continue;
                    benefit = damage;
                } else {
                    if (friends || (item == "Свет" &&
                                    ((!backup && !vulnerable) || (coordination && flash_reserved(target)))))
                        continue;
                    double sum = 0, error = 0;
                    for (auto &id : a.at("visible")) {
                        double d = distance(actor_point(a.at("knowledge").at(id.get<std::string>())), target);
                        if (d < radius) {
                            double x = item == "Свет" ? damage : (1 - d / radius) * (item == "HE" ? 82 : 30),
                                   t;
                            if (coordination && item == "Свет") {
                                const Json &sight = a.at("knowledge").at(id.get<std::string>());
                                const Point eye = actor_point(sight);
                                const double heading =
                                    sight.contains("bodySector")
                                        ? sight.at("bodySector").get<int>() * std::numbers::pi / 4.
                                        : std::atan2(pos[1] - eye[1], pos[0] - eye[0]);
                                x *= nav.hit(target, eye, 1, 5, 64)
                                         ? 0.
                                         : flash_exposure(eye, heading, target, radius);
                                x *= 1. / (1. + (flight + warn) * sight.value("speed", 0.) / radius);
                            }
                            t = sum + x;
                            error += std::abs(sum) >= std::abs(x) ? (sum - t) + x : (x - t) + sum;
                            sum = t;
                        }
                    }
                    benefit = sum + error;
                    if (item == "HE" && a.contains("confirmedHit") &&
                        a.at("confirmedHit").at("id") == contact.at("id") &&
                        now - a.at("confirmedHit").at("tick").get<Tick>() <= 16)
                        benefit += damage * .3;
                }
                double mastery =
                           skills.at(cfg.at("grenadeSkills").at(item).get<std::string>()).get<double>() / 100,
                       exposure = std::max(0., 1 - contact.value("speed", 0.) * flight / radius);
                auto candidate = std::pair{benefit * (1 - mastery * (1 - exposure)), item};
                if (!best || candidate > *best)
                    best = candidate;
            }
            if (best && best->first > opportunity * skills.at("decisions").get<int>() / 100 &&
                distance(nav.grenade(pos, target, flight).back(), target) <
                    cfg.at("utility").at(best->second)[0].get<double>()) {
                auto result = contact;
                result["utility"] = best->second;
                if (coordination)
                    result["purpose"] = "Граната в дуэли";
                return Json::array({"throw", result});
            }
        }
    }
    if (a.at("reloadAt") == 0 && a.at("ammo") != 0 && now >= a.at("ready").get<Tick>())
        return Json::array({"shoot", contact});
    return Json::array({"hold", nullptr});
}
Json AgentTurn::last_burst() {
    const auto &nav = arena.objectives().map();
    const auto &spec = cfg.at("weapons").at(a.at("weapon").get<std::string>());
    if (!a.at("target").is_string() || a.at("ammo").get<int>() <= spec.at("mag").get<int>() / 2 ||
        a.at("reloadAt") != 0 || now < a.at("ready").get<Tick>() || a.at("blind") > now || !action.empty())
        return nullptr;
    auto id = a.at("target").get<std::string>();
    if (!a.at("knowledge").contains(id))
        return nullptr;
    auto sight = a.at("knowledge").at(id);
    auto age = now - sight.at("tick").get<Tick>();
    const bool screen =
        spatial_grenades(w) && age <= 9 && std::ranges::any_of(w.at("effects"), [&](const Json &f) {
            return f.at("kind") == "Дым" && f.at("land") <= now &&
                   crosses_volume(f, actor_point(a), actor_point(sight));
        });
    if (sight.at("source") != "Зрение" || age <= 0 || age > (screen ? 9 : 3))
        return nullptr;
    auto dir = sight.value("direction", Point{0, 0, 0}), origin = actor_point(sight), q = origin;
    double delta =
        std::min(2., sight.value("speed", 0.)) * age * (skills.at("game_reading").get<double>() / 100);
    for (int i = 0; i < 3; ++i)
        q[i] += dir[i] * delta;
    if (q != origin && nav.hit(origin, q, 1, 56, 56))
        q = origin;
    if (std::ranges::any_of(
            squad, [&](auto m) { return m != &a && near_segment(actor_point(a), q, actor_point(*m), 2); }))
        return nullptr;
    sight["x"] = q[0];
    sight["y"] = q[1];
    sight["z"] = q[2];
    if (screen)
        sight.erase("id");
    a["status"] = screen ? "Простреливает дым по памяти" : "Продолжает очередь по последнему контакту";
    return Json::array({"shoot", sight});
}
} // namespace esport
