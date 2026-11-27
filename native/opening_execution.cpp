#include "grenades.hpp"
#include "agent_helpers.hpp"
#include "radio.hpp"
namespace esport {
namespace {
const Json *opening_watch(const AgentTurn &t) {
    Reports rs;
    for (auto &r : t.a.at("knowledge")) {
        Tick age = t.now - r.at("tick").get<Tick>();
        if ((r.at("source") == "Радио" || r.at("source") == "Слух") && age >= 0 &&
            age <= 12 + t.skills.at("game_reading").get<int>() / 9 &&
            t.gap(r) <= (active(r, "sound") ? 94 : 80))
            rs.push_back(&r);
    }
    auto rank = [](const Json *r) {
        return std::tuple{!active(*r, "carryingC4"), r->at("source") == "Слух", -r->at("tick").get<Tick>()};
    };
    std::stable_sort(rs.begin(), rs.end(), [&](auto l, auto r) { return rank(l) < rank(r); });
    for (auto r : rs) {
        if (r->value("witness", Json(nullptr)) == t.a.at("id"))
            return r;
        const Json *best = nullptr;
        auto key = [&](const Json &a) {
            return std::pair{distance(actor_point(a), actor_point(*r)), a.at("slot").get<int>()};
        };
        for (auto p : t.squad)
            if ((t.individual && p != &t.a ? !t.observed_aim(*p) : p->at("visible").empty()) &&
                ((small_groups(t.w) && p != &t.a) || p->at("blind") <= t.now) &&
                p->at("id") != r->value("witness", Json(nullptr)) &&
                p->at("id") != r->value("reporter", Json(nullptr)) && (!best || key(*p) < key(*best)))
                best = p;
        if (best == &t.a)
            return r;
    }
    return nullptr;
}
} // namespace
Json AgentTurn::opening_decision() {
    const auto &nav = arena.objectives().map();
    auto &op = plan.at("opening"), &jobs = op.at("jobs");
    auto id = a.at("id").get<std::string>();
    auto &job = jobs.at(id);
    if (!job.contains("gate") ||
        (active(a, "plantCue") && now - a.at("plantCue").at("tick").get<Tick>() < 30))
        return nullptr;
    Point pos = actor_point(a), gate = job.at("gate"), peek = job.at("peek"), watch = job.at("watch");
    auto lookup = [&](const Json &pid) -> Json * {
        for (auto m : squad)
            if (m->at("id") == pid)
                return m;
        return nullptr;
    };
    auto support = lookup(job.value("partner", Json(nullptr)));
    if (support && relief(plan, *support))
        support = nullptr;
    if (relief(plan, a) || plan.at("reinforce") == job.at("site")) {
        job["reason"] = "Приказ на усиление";
        return nullptr;
    }
    if (a.at("hp") < 35 || a.value("blockedTicks", 0) >= 6) {
        job["reason"] = "Ранение или потеря маршрута";
        job["withdrawn"] = true;
    }
    if (active(job, "withdrawn"))
        return nullptr;
    bool fresh = false;
    for (auto &r : a.at("knowledge"))
        if (now - r.at("tick").get<Tick>() < 30 && visual(r)) {
            fresh = true;
            auto p = actor_point(r);
            if (distance(p, job.at("home").get<Point>()) < distance(p, peek) &&
                arena.objectives().reported_site(p) == job.at("site").get<std::string>()) {
                job["reason"] = "Обошли передовую позицию";
                return nullptr;
            }
        }
    if (!small_groups(w) && support && active(jobs.at(support->at("id").get<std::string>()), "withdrawn"))
        support = nullptr;
    auto gate_ready = [&]() {
        if (!support)
            return false;
        auto message = recent_call(support->at("id"), "gate", 22);
        return message && message->at("state") == "set" && message->at("order") == job.at("zone") &&
               distance(actor_point(*support), message->at("origin").get<Point>()) < 5;
    };
    auto towards = [&](const Point &goal, const std::string &status,
                       std::optional<Point> aim = std::nullopt) {
        a["status"] = status + " · " + job.at("zone").get<std::string>();
        bool moved = distance(pos, goal) > 3 && move(goal, 2);
        Point look = aim.value_or(watch);
        if (!moved || distance(pos, goal) < 24) {
            auto cast = job.value("throw", Json::object());
            bool flash = cast.value("item", std::string{}) == "Свет" && !cast.contains("skip") &&
                         now < cast.value("land", now + 1);
            if (!moved && !flash)
                if (auto report = opening_watch(*this)) {
                    look = actor_point(*report);
                    a["status"] = (report->at("source") == "Слух" ? "Слушает направление · "
                                                                  : "Проверяет по радио · ") +
                                  job.at("zone").get<std::string>();
                }
            heading_to(a, look);
        }
        return Json::array({moved ? "move" : "hold", nullptr});
    };
    if (op.at("quiet") == true && job.at("zone") != op.at("focus")[0] && !active(job, "coverOrder") &&
        !active(job, "release"))
        return towards(job.at("home"), "Держит внутренний рубеж",
                       plan.at("orders").at("slots").at(slot).at("watch").get<Point>());
    if (active(job, "coverOrder") && now < job.at("coverOrder").at("until").get<Tick>())
        return towards(job.at("coverOrder").at("goal"), "Сменяет напарника",
                       job.at("coverOrder").at("watch").get<Point>());
    job.erase("reason");
    if (active(job, "throw")) {
        auto &cast = job.at("throw");
        if (!cast.contains("land") && !cast.contains("skip")) {
            std::string item = cast.at("item");
            Point target = cast.at("target"), launch = cast.at("launch");
            if (!member_of(a.at("utility"), item) || now - plan.at("start").get<Tick>() > 260)
                cast["skip"] = "Расход или истёк интервал";
            else if (cast.at("forPlayer") != id && !support)
                cast["skip"] = "Напарник недоступен";
            else if (distance(pos, launch) > 3)
                return towards(launch, "Занимает позицию броска");
            else {
                if (item == "Свет" && support &&
                    (small_groups(w) ? !gate_ready() : now < jobs.at(support->at("id").get<std::string>()).value("atGate", now + 1))) {
                    if (now - plan.at("start").get<Tick>() < 175)
                        return towards(pos, "Ждёт готовности выхода", gate);
                    cast["skip"] = "Напарник не вышел на рубеж";
                    return towards(gate, "Занимает страховку");
                }
                int flight = std::max(3, int(std::nearbyint(distance(pos, target) / 7)));
                if (distance(nav.grenade(pos, target, flight).back(), target) >= 6) {
                    if (distance(pos, launch) > .5) {
                        move(launch, 1);
                        return Json::array({"move", nullptr});
                    }
                    cast["skip"] = "Линия броска перекрыта";
                } else if (std::ranges::any_of(squad, [&](auto m) {
                               if (item == "Свет" && spatial_grenades(w))
                                   return flash_risk(*m, target, flight);
                               return distance(actor_point(*m), target) <
                                          cfg.at("utility").at(item)[0].get<double>() + 2 &&
                                      !nav.hit(actor_point(*m), target, 1, 64, 64);
                           }))
                    cast["skip"] = "Союзник в зоне гранаты";
                else if (now >= a.at("throwAt").get<Tick>() && a.at("blind") <= now) {
                    auto intent =
                        grenade_intent(target, item, "Занятие " + job.at("zone").get<std::string>());
                    intent[1]["openingZone"] = job.at("zone");
                    return intent;
                }
            }
        }
    }
    int delay = 1 + (100 - skills.at("communication").get<int>()) / 12;
    if (distance(pos, gate) < 5 && !job.contains("atGate"))
        job["atGate"] = now + delay;
    if (!job.contains("atGate"))
        return towards(gate, "Выходит на рубеж");
    if (distance(pos, gate) < 5 && job.at("atGate") <= now)
        job["lastCover"] = now;
    const Json *other = support ? &jobs.at(support->at("id").get<std::string>()) : nullptr;
    if (job.at("role") == "страховка" && other) {
        auto aim = individual ? observed_aim(*support) : nullptr;
        auto target_id = individual ? (aim ? aim->at("id") : Json(nullptr)) : support->at("target");
        if (target_id.is_string()) {
            auto target = target_id.get<std::string>();
            if (a.at("knowledge").contains(target)) {
                const auto &r = a.at("knowledge").at(target);
                if (now - r.at("tick").get<Tick>() < 25) {
                    a["tradeTarget"] = r.at("id");
                    a["tradeUntil"] = now + 12;
                    return towards(gate, "Готовит размен", actor_point(r));
                }
            }
        }
        if ((small_groups(w) || active(*other, "departed")) && distance(actor_point(*support), peek) < 8)
            return towards(gate, "Страхует занятую зону", watch);
        return towards(gate, "Прикрывает выход напарника", peek);
    }
    if (!other)
        if (auto replacement = lookup(job.value("replacement", Json(nullptr)))) {
            auto order =
                jobs.at(replacement->at("id").get<std::string>()).value("coverOrder", Json::object());
            if (!relief(plan, *replacement) && order.value("forPlayer", std::string{}) == id &&
                distance(actor_point(*replacement), gate) < 6)
                return towards(peek, "Проверяет под сменную страховку");
        }
    if (active(job, "partner") && !other) {
        job["reason"] = "Нет страховки";
        return towards(gate, "Держит до смены напарника");
    }
    if (other && small_groups(w)) {
        bool flash = false, in_flight = false;
        if (a.contains("crossingCalls"))
            for (const auto &cast : a.at("crossingCalls")) {
                if (cast.value("forPlayer", std::string{}) != id || cast.at("item") != "Свет")
                    continue;
                const Tick land = cast.at("land");
                flash |= land <= now && now <= land + 12;
                in_flight |= now < land;
            }
        const bool armed = a.at("blind") <= now && a.at("ready") <= now && !active(a, "reloadAt") && a.at("ammo") > 0;
        if (!armed || (!gate_ready() && !flash) || in_flight)
            return towards(gate, "Ждёт страховку");
    } else if (other) {
        auto pending = other->value("throw", Json::object());
        auto land = pending.value("land", Tick{-100});
        bool window = land <= now && now <= land + 12 && pending.value("item", std::string{}) == "Свет";
        if ((!window && now - other->value("lastCover", Tick{-100}) > 25) ||
            (pending.contains("item") && !pending.contains("skip") && now < pending.value("land", now + 1)))
            return towards(gate, "Ждёт страховку");
    }
    if (group_tasks(w) && other && (!job.contains("departed") ||
        (active(a, "groupLead") && !a.at("groupLead").value("closed", false)))) {
        auto paired = coordinated_peek(peek, Json::array({"opening", job.at("zone"), gate}),
                                       !job.contains("departed"), support->at("id"));
        if (!paired.is_null()) {
            if (paired.at(0) == "move")
                job["departed"] = now;
            return paired;
        }
    }
    if (!job.contains("departed"))
        job["departed"] = now;
    auto &reports = op.at("reports");
    if (distance(pos, peek) < 6 && !fresh && opening_sight && a.at("blind") <= now &&
        in_range_fov(a, watch)) {
        if (!reports.contains(id) || now - reports.at(id).at("due").get<Tick>() > 65) {
            reports[id] = Json{{"zone", job.at("zone")}, {"observed", now}, {"due", now + delay}};
            if (small_groups(w))
                signal_group("survey", "checked", watch, job.at("zone"));
            job["rechecks"] = job.value("rechecks", 0) + 1;
        }
    }
    if (active(job, "holdsFor")) {
        auto &relieving = jobs.at(job.at("holdsFor").get<std::string>());
        const bool checked = small_groups(w) ? recent_call(job.at("holdsFor"), "survey", 30) != nullptr
                                             : active(relieving, "rechecks");
        if (now - relieving.value("handoffAt", Tick{0}) < 65 && !checked)
            return towards(peek, "Прикрывает смену позиции");
    }
    if (reports.contains(id)) {
        auto age = now - reports.at(id).at("due").get<Tick>();
        if (age >= 20 && age < 43)
            return towards(gate, "Меняет угол после проверки");
    }
    return towards(peek, distance(pos, peek) > 5 ? "Проверяет направление" : "Наблюдает подход");
}
} // namespace esport
