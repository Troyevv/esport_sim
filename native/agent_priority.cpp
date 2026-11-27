#include "grenades.hpp"
#include "agent_helpers.hpp"
#include "radio.hpp"
namespace esport {
Json AgentTurn::priority_intent() {

    if (spatial_grenades(w)) {
        auto reaction = utility_response();
        if (!reaction.is_null())
            return reaction;
    }
    auto intent = individual ? personal_decision() : contact_decision();
    if (!intent.is_null())
        return intent;
    if (grid)
        return grid_intent();
    const auto &nav = arena.objectives().map();
    const bool rescuing = side == "T" && !device.empty() && device.at("carrier").is_null() &&
                          device.at("site").is_null() && !recovery.empty() &&
                          recovery.at("player") == a.at("id");
    const bool reinforce = side == "CT" && (w.at("phase") == "planted" || relief(plan, a));
    bool board = active(plan, "board");
    if (side == "T" && w.at("phase") == "live" && !rescuing && !board && action.empty() &&
        plan.contains("commandJobs")) {
        const auto &jobs = plan.at("commandJobs");
        const auto it = jobs.find(a.at("id").get<std::string>());
        if (it != jobs.end()) {
            const auto &duty = *it;
            const auto &kind = plan.at("commandKind");
            const Point goal = duty.at("point");
            const auto pos = actor_point(a);
            if (!device.empty() && device.at("carrier") == a.at("id") && arena.objectives().site_at(pos))
                return nullptr; // Let the objective executor take the plant.
            if (kind == "feint") {
                if (!a.value("feintThrown", false) && distance(pos, goal) < 48) {
                    auto order = plan.at("orders").at("slots").at(slot);
                    order["lane"] = duty.at("lane");
                    auto cast = crossing(order, duty.at("site"));
                    if (!cast.is_null())
                        return cast;
                }
                a["status"] = "Давит на ложный вход";
            } else if (kind == "regroup")
                a["status"] = "Перестраивается по парам";
            else if (kind == "save")
                a["status"] = "Сохраняет оружие до конца раунда";
            else
                a["status"] = "Занимает дополнительный рубеж";
            if (distance(pos, goal) > 5)
                return movement(goal, kind == "space" ? 1.65 : 2.);
            heading_to(a, duty.at("watch"));
            return Json::array({"hold", nullptr});
        }
    }
    auto pos = actor_point(a);
    if (!rescuing && !board && !reinforce && (!collective_attack(w) || action.empty()) && squad.size() < 5 && a.at("playingRole") == "support" &&
        side == "T" && w.at("phase") == "live" && (device.empty() || device.at("carrier") != a.at("id"))) {
        const auto &slots = plan.at("orders").at("slots");
        auto lane = slots.at(slot).at("lane");
        Json *partner = nullptr;
        auto rank = [&](const Json *mate) {
            auto readiness = (skills.at("support").get<int>() + skills.at("coordination").get<int>() +
                              chemistry(w, a, *mate)) /
                             300.;
            int need = mate->at("playingRole") == "entry";
            if (small_groups(w)) {
                auto report = recent_call(mate->at("id"), "contact", 25);
                need += report && report->at("state") == "help" && report->contains("members") &&
                        !report->at("members").empty() &&
                        report->at("members").front() == a.at("id");
            } else
                need += mate->at("reloadAt") != 0 || mate->at("hp") < a.at("hp");
            return std::pair{need * readiness - gap(*mate) / 100, -mate->at("slot").get<int>()};
        };
        for (auto m : squad)
            if (m != &a && slots.at(m->at("slot").get<int>()).at("lane") == lane &&
                (!partner || rank(m) > rank(partner)))
                partner = m;
        if (!partner)
            partner = &a;
        if (gap(*partner) > 75 - skills.at("support").get<int>() * .45 - chemistry(w, a, *partner) * .15) {
            auto target = actor_point(*partner);
            Json goal;
            if (active(a, "rendezvous") && a.at("rendezvous").at("mate") == partner->at("id") &&
                now < a.at("rendezvous").at("review").get<Tick>() &&
                distance(a.at("rendezvous").at("location").get<Point>(), target) < 14 &&
                !active(a, "blockedTicks"))
                goal = a.at("rendezvous").at("point");
            else {
                auto spots = nearby_points(nav, target, 23);
                std::erase_if(spots, [&](auto &q) { return bool(nav.hit(q, target, 1, 64, 64)); });
                auto key = [&](const Point &q) {
                    auto d = distance(q, target);
                    return std::pair{d < 6 || d > 20, distance(pos, q) + d};
                };
                std::stable_sort(spots.begin(), spots.end(),
                                 [&](auto &p, auto &q) { return key(p) < key(q); });
                spots.push_back(target);
                if (auto q = first_reachable(nav, pos, spots))
                    goal = *q;
                a["rendezvous"] = Json{
                    {"mate", partner->at("id")}, {"review", now + 18}, {"location", target}, {"point", goal}};
            }
            if (!goal.is_null()) {
                a["status"] = "Поддерживает партнёра на выходе";
                bool moved = move(goal, 2);
                if (moved || !active(a, "blockedTicks"))
                    return Json::array({moved ? "move" : "hold", nullptr});
            }
        }
    }
    if (board && w.at("phase") != "planted" && plan.at("rotated") == false && !rescuing && !reinforce) {
        intent = board_step(w, a, cfg, arena.objectives(), device, fire);
        if (!intent.is_null())
            return intent;
    }
    if (side == "CT" && w.at("phase") == "live" && active(plan, "opening"))
        return opening_decision();
    if (side == "T" && w.at("phase") == "live" && !device.empty() && !device.at("carrier").is_null() &&
        action.empty())
        return hold_sector();
    return nullptr;
}
} // namespace esport
