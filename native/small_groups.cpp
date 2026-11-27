#include "agent_helpers.hpp"
#include "radio.hpp"

namespace esport {
const Json *AgentTurn::recent_call(const Json &sender, const std::string &channel, int lifetime) const {
    auto calls = a.find("peerCalls");
    if (!sender.is_string() || calls == a.end())
        return nullptr;
    auto call = calls->find(sender.get<std::string>() + "/" + channel);
    if (call == calls->end())
        return nullptr;
    auto age = now - call->at("tick").get<Tick>();
    return age >= 0 && age < lifetime ? &*call : nullptr;
}

// Everyone hears the same nomination. Only the named mobile player can leave
// a post. The optional third member covers from the position they already own.
Json AgentTurn::group_members(const Point &origin) const {
    const auto &slots = plan.at("orders").at("slots");
    const auto &home = slots.at(slot);
    std::vector<std::tuple<double, int, std::string>> choices;
    for (auto mate : squad) {
        if (mate == &a)
            continue;
        const auto &id = mate->at("id");
        const double d = distance(actor_point(*mate), origin); // teammate radar
        if (d > 60 || (!device.empty() && device.value("carrier", Json(nullptr)) == id))
            continue;
        auto reply = recent_call(id, "support", 18);
        if (reply && (reply->at("state") == "decline" || reply->at("order").at(0) != a.at("id")))
            continue;
        auto report = recent_call(id, "order", 30);
        if (report && (report->at("state") == "refused" || report->at("state") == "unavailable" ||
                       !report->value("armed", true)))
            continue;
        const int seat = mate->at("slot");
        const auto &job = slots.at(seat);
        const auto role = mate->at("playingRole").get<std::string>();
        if (!grid && side == "CT" && job.at("site") != home.at("site"))
            continue;
        const auto &profile = player_profile(w, *mate);
        double score = -d + chemistry(w, a, *mate) / 8. + profile.at("roleMastery").value(role, 0) / 12.;
        score += (role == "support" ? 5 : 0) + (report && report->value("hasUtility", false) ? 4 : 0);
        if (!grid && side == "T" && home.at("lane") == job.at("lane"))
            score += 18;
        choices.emplace_back(-score, seat, id.get<std::string>());
    }
    std::sort(choices.begin(), choices.end());
    Json members = Json::array();
    for (const auto &[score, seat, id] : choices) {
        members.push_back(id);
        if (members.size() == 2)
            break;
    }
    return members;
}

void AgentTurn::signal_group(const std::string &channel, const std::string &state, const Point &point,
                            const Json &order) {
    if (channel == "support" && state == "decline")
        a["declinedSupport"][order.at(0).get<std::string>()] = order.at(1);
    auto &last = a["sentFeedback"][channel];
    if (!last.is_null() && last.at("state") == state && last.at("order") == order &&
        distance(last.at("origin").get<Point>(), actor_point(a)) < 5 && now - last.at("tick").get<Tick>() < 10)
        return;
    last = {{"channel", channel}, {"state", state}, {"tick", now}, {"origin", actor_point(a)},
            {"point", point}, {"order", order}};
    w.at("messages").push_back({{"team", side}, {"sender", a.at("id")}, {"feedback", last},
                                {"due", now + 1 + (100 - skills.at("communication").get<int>()) / 12}});
}

bool AgentTurn::group_lane(const Point &point) const {
    const auto pos = actor_point(a);
    return a.at("blind") <= now && a.at("reloadAt") == 0 && a.at("ammo") > 0 && a.at("ready") <= now &&
           in_range_fov(a, point) &&
           (grid ? grid->clear(xy(a), {point[0], point[1]}) : !arena.objectives().map().hit(pos, point, 1, 64, 64)) &&
           std::ranges::none_of(w.at("effects"), [&](const Json &f) {
               return f.at("kind") == "Дым" && f.at("land") <= now && now < f.at("end") &&
                      near_segment(pos, point, actor_point(f), f.at("radius"));
           });
}

Json AgentTurn::group_assist(const Json &request) {
    const auto origin = request.at("origin").get<Point>(), point = request.at("point").get<Point>();
    const Json task = Json::array({request.at("sender"), request.at("tick")});
    const auto &primary = request.at("members").front();
    const auto response = recent_call(primary, "support", 18);
    const bool released = response && response->at("state") == "decline" && response->at("order") == task;
    const bool primary_alive = std::ranges::any_of(squad, [&](auto m) { return m->at("id") == primary; });
    const bool mobile = primary == a.at("id") ? !released : !primary_alive || released;
    const auto mate = std::ranges::find_if(squad, [&](auto m) { return m->at("id") == request.at("sender"); });
    auto declined = a.find("declinedSupport");
    if (declined != a.end() && declined->value(request.at("sender").get<std::string>(), Tick{-1}) == request.at("tick"))
        return nullptr;
    if (mobile && mate != squad.end() && !grid && request.at("state") == "help" &&
        now >= a.at("throwAt") && !a.at("utility").empty()) {
        // Use only the quoted sight and a locally delivered request.
        auto report = a.at("knowledge").find(request.at("order").get<std::string>());
        if (report != a.at("knowledge").end()) {
            auto cast = assist_contact({*mate}, *report);
            if (!cast.empty()) {
                cast[1]["purpose"] = "Поддержка по запросу напарника";
                return cast;
            }
        }
    }
    if (mobile && mate != squad.end() && (request.at("state") == "help" || request.at("state") == "stage") &&
        distance(actor_point(a), origin) > 14) {
        const bool moved = grid ? grid->walk(a, Json::array({origin[0], origin[1]}), 2 * move_speed(player), grid_fire, true)
                                : move(origin, 2);
        signal_group("support", moved ? "joining" : "decline", point, task);
        if (!moved)
            return nullptr;
        a["status"] = "Идёт на запрос помощи";
        return Json::array({"move", nullptr});
    }
    const double prior_heading = a.at("heading");
    heading_to(a, point);
    const bool ready = group_lane(point);
    if (mobile)
        signal_group("support", ready ? "set" : "decline", point, task);
    if (!ready) {
        a["heading"] = prior_heading;
        return nullptr;
    }
    a["status"] = mate == squad.end() ? "Принимает сектор напарника" :
                  mobile ? "Прикрывает направление по радио" : "Страхует группу со своей позиции";
    return Json::array({"hold", nullptr});
}

Json AgentTurn::stage_pair(const Point &goal, bool arrived) {
    // A waypoint is an actual arrival. Bound the pause to a single radio
    // exchange, and leave the individual executor in charge during contact.
    if (arrived && a.at("visible").empty() && a.at("ammo") > 0 &&
        (a.at("playingRole") == "entry" || a.at("playingRole") == "rifler")) {
        auto members = group_members(actor_point(a));
        if (!members.empty()) {
            Point look = actor_point(a);
            const double scale = std::min(1., 14 / std::max(1., distance(look, goal)));
            for (size_t i = 0; i < look.size(); ++i)
                look[i] += (goal[i] - look[i]) * scale;
            Json msg = {{"channel", "stage"}, {"state", "stage"}, {"tick", now}, {"origin", actor_point(a)},
                        {"point", look}, {"members", members}, {"order", a.at("waypoint")}};
            a["sentFeedback"]["stage"] = msg;
            w.at("messages").push_back({{"team", side}, {"sender", a.at("id")}, {"feedback", msg},
                                        {"due", now + 1 + (100 - skills.at("communication").get<int>()) / 12}});
        }
    }
    if (!a.contains("sentFeedback") || !a.at("sentFeedback").contains("stage"))
        return nullptr;
    const auto &request = a.at("sentFeedback").at("stage");
    if (request.at("order") != a.at("waypoint") || now - request.at("tick").get<Tick>() >= 18 ||
        distance(actor_point(a), request.at("origin").get<Point>()) > 5)
        return nullptr;
    const Json task = Json::array({a.at("id"), request.at("tick")});
    for (const auto &id : request.at("members")) {
        auto mate = std::ranges::find_if(squad, [&](auto m) { return m->at("id") == id; });
        if (mate == squad.end())
            continue;
        auto reply = recent_call(id, "support", 18);
        if (reply && reply->at("order") == task) {
            if (reply->at("state") == "decline")
                continue;
            if (reply->at("state") == "set" && a.at("blind") <= now && a.at("reloadAt") == 0 &&
                a.at("ammo") > 0 && a.at("ready") <= now && distance(actor_point(**mate), reply->at("origin").get<Point>()) < 5) {
                a["status"] = "Выходит под прикрытие напарника";
                return movement(goal, 2);
            }
        }
        heading_to(a, request.at("point"));
        a["status"] = "Ждёт прикрытия на рубеже";
        return Json::array({"hold", nullptr});
    }
    return nullptr;
}
} // namespace esport
