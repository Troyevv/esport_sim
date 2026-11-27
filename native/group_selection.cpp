#include "group_tasks.hpp"
#include <limits>

namespace esport {
Tick AgentTurn::offer_deadline(bool urgent) const {
    // Budget two radio trips and a short approach, within the objective clock.
    return std::min(w.at("deadline").get<Tick>() - 3, now + (urgent ? 15 : 21) + 2 * radio_delay(*this));
}

bool AgentTurn::protects_sector(const Json &actor) const {
    if (grid || side != "CT" || w.at("phase") != "live")
        return false;
    const auto &slots = plan.at("orders").at("slots");
    const auto &job = slots.at(actor.at("slot").get<int>());
    const Point hold = job.at("hold");
    if (relief(plan, actor) || distance(actor_point(actor), hold) > 24)
        return false;
    return std::ranges::none_of(squad, [&](const Json *mate) {
        return mate != &actor && slots.at(mate->at("slot").get<int>()).at("site") == job.at("site") &&
               distance(actor_point(*mate), hold) <= 32;
    });
}

bool AgentTurn::cover_from_place(const Json &actor, const Point &origin, const Point &aim) const {
    const Point pos = actor_point(actor);
    if (distance(pos, origin) > 30)
        return false;
    if (grid)
        return grid->clear(xy(actor), {aim[0], aim[1]}) && grid->clear(xy(actor), {origin[0], origin[1]});
    const auto &nav = arena.objectives().map();
    return !nav.hit(pos, aim, 1, 64, 64) && !nav.hit(pos, origin, 1, 64, 64);
}

namespace {
double approach(const AgentTurn &t, const Json &mate, const Point &origin) {
    Point pos = actor_point(mate);
    if (t.grid) {
        auto from = t.grid->cell(xy(mate)), to = t.grid->cell({origin[0], origin[1]});
        if (from == to)
            return distance(pos, origin);
        auto steps = t.grid->route(from, to);
        return steps.empty() ? std::numeric_limits<double>::infinity()
                             : std::max(distance(pos, origin), t.grid->unit * steps.size());
    }
    const auto &nav = t.arena.objectives().map();
    // Both endpoints are teammate radar poses. path() uses the physical portal
    // and positioned path caches, including negative answers.
    auto path = nav.path(mate.at("navArea"), pos, t.a.at("navArea"), origin, {});
    if (!path)
        return std::numeric_limits<double>::infinity();
    double length = 0;
    for (auto [x, y, z, area] : *path) {
        Point next{x, y, z};
        length += distance(pos, next);
        pos = next;
    }
    return length;
}
} // namespace

Json AgentTurn::nominate_group(const Point &origin, const Point &aim, Tick until) const {
    const auto &slots = plan.at("orders").at("slots");
    const auto &home = slots.at(slot);
    std::vector<std::tuple<double, int, std::string>> choices;
    const auto calls = a.find("peerCalls");
    for (auto mate : squad) {
        if (mate == &a)
            continue;
        const auto &id = mate->at("id");
        const int seat = mate->at("slot");
        const auto &job = slots.at(seat);
        const auto pos = actor_point(*mate);
        auto report = recent_call(id, "order", 30);
        if ((!device.empty() && device.value("carrier", Json(nullptr)) == id) ||
            (report && (!report->value("armed", true) || report->at("state") == "unavailable")) ||
            (!grid && side == "CT" && job.at("site") != home.at("site")))
            continue;
        bool busy = false;
        if (calls != a.end())
            for (const auto &r : *calls)
                if (r.at("sender") == id && r.contains("duty") && !terminal_reply(r.at("state")) &&
                    r.at("until") > now && r.at("order").at(0) != a.at("id"))
                    busy = true;
        if (busy)
            continue;
        const double range = distance(pos, origin);
        const bool standing = cover_from_place(*mate, origin, aim);
        const auto &profile = player_profile(w, *mate);
        const double speed = 2 * move_speed(profile);
        const double budget = std::max<Tick>(0, until - now - radio_delay(*this));
        if (!standing && (range > speed * budget + 12 || protects_sector(*mate)))
            continue;
        const double eta = standing ? 0 : std::max(0., approach(*this, *mate, origin) - 12) / speed;
        if (eta > budget)
            continue;
        auto role = mate->at("playingRole").get<std::string>();
        double cost =
            eta + range / 5 - chemistry(w, a, *mate) / 9. - profile.at("roleMastery").value(role, 0) / 12.;
        if (active(plan, "board") || relief(plan, *mate) || (report && report->at("state") == "ready"))
            cost += standing ? 2 : 16;
        if (auto threat = recent_call(id, "contact", 15); threat && threat->at("state") == "help")
            cost += 20;
        if (role == "support" || (report && report->value("hasUtility", false)))
            cost -= 5;
        if (!grid && side == "T" && home.at("lane") == job.at("lane"))
            cost -= 8;
        choices.emplace_back(cost, seat, id.get<std::string>());
    }
    std::sort(choices.begin(), choices.end());
    Json members = Json::array();
    for (const auto &[cost, seat, id] : choices) {
        members.push_back(id);
        if (members.size() == 2)
            break;
    }
    return members;
}
} // namespace esport
