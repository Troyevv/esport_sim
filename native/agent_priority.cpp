#include "agent_helpers.hpp"
namespace esport {
Json AgentTurn::priority_intent() {

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
    auto pos = actor_point(a);
    if (!rescuing && !board && !reinforce && squad.size() < 5 && a.at("playingRole") == "support" &&
        side == "T" && w.at("phase") == "live" && (device.empty() || device.at("carrier") != a.at("id"))) {
        const auto &slots = plan.at("orders").at("slots");
        auto lane = slots.at(slot).at("lane");
        Json *partner = nullptr;
        auto rank = [&](const Json *mate) {
            auto readiness = (skills.at("support").get<int>() + skills.at("coordination").get<int>() +
                              chemistry(w, a, *mate)) /
                             300.;
            int need = (mate->at("reloadAt") != 0 || mate->at("hp") < a.at("hp")) +
                       (mate->at("playingRole") == "entry");
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
