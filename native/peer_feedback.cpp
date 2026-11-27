#include "agent_helpers.hpp"
#include "radio.hpp"

namespace esport {
namespace {
void announce(AgentTurn &turn, const char *channel, const char *state, const Point &point, Json order) {
    auto &a = turn.a;
    auto &last = a["sentFeedback"][channel];
    const bool urgent = std::string_view(state) == "refused" || std::string_view(state) == "completed";
    if (!last.is_null()) {
        auto age = turn.now - last.at("tick").get<Tick>();
        if (!urgent && age < 6)
            return;
        if (last.at("state") == state && last.at("order") == order && last.value("waypoint", 0) == a.value("waypoint", 0) &&
            distance(last.at("point").get<Point>(), point) < 10 &&
            (age < 30 || std::string_view(state) == "ack"))
            return;
    }
    last = {{"state", state}, {"order", std::move(order)}, {"point", point}, {"origin", actor_point(a)},
            {"tick", turn.now}, {"channel", channel}, {"waypoint", a.value("waypoint", 0)}};
    if (std::string_view(state) == "refused")
        last["reason"] = a.at("lastRefusal").at("reason");
    const int skill = turn.skills.at("communication");
    turn.w.at("messages").push_back({{"team", turn.side}, {"sender", a.at("id")}, {"feedback", last},
                                     {"due", plus_ticks(turn.now, 1 + (100 - skill) / 12)}});
}
}

void AgentTurn::peer_feedback(const std::string &kind) {
    // A request quotes a firsthand observation only. A received request or
    // a radio contact can never itself trigger another request.
    if (now % 4 == slot % 4 && a.at("blind") <= now) {
        if (!a.at("visible").empty() && (a.at("visible").size() > 1 || a.at("hp") < 65 ||
                                         a.at("reloadAt") > now || !a.at("ammo").get<int>())) {
            const auto id = a.at("visible").front().get<std::string>();
            announce(*this, "contact", "help", actor_point(a.at("knowledge").at(id)), id);
        } else if (a.at("visible").empty()) {
            for (const auto &r : a.at("knowledge")) {
                const Tick age = now - r.at("tick").get<Tick>();
                if (r.at("source") == "Зрение" && age > 0 && age <= 4) {
                    announce(*this, "contact", "check", actor_point(r), r.at("id"));
                    break;
                }
            }
        }
    }
    const bool refused = a.contains("lastRefusal") && a.at("lastRefusal").at("tick") == now;
    const bool completed = a.value("stepIndex", 0) != step_index;
    if (!refused && !completed && now % 8 != slot)
        return;
    const auto &slot_order = plan.at("orders").at("slots").at(slot);
    const auto &order = !grid && side == "CT" ? assignment(plan, a, squad) : slot_order;
    const auto &hold = order.at("hold");
    Point goal{hold.at(0), hold.at(1), hold.size() > 2 ? hold.at(2).get<double>() : 0.};
    Json task = Json::array({w.at("phase"), order.value("site", plan.at("site")), goal});
    if (active(plan, "retake") && plan.at("retake").at("duties").contains(a.at("id").get<std::string>())) {
        const auto &duty = plan.at("retake").at("duties").at(a.at("id").get<std::string>());
        goal = duty.at("stage").get<Point>();
        task = Json::array({"retake", plan.at("retake").at("site"), goal});
    }
    if (active(plan, "board") && !active(plan, "rotated") && w.at("phase") == "live") {
        const auto &board = plan.at("board");
        const auto &steps = board.at("slots").at(slot);
        if (size_t(step_index) < steps.size()) {
            goal = actor_point(steps.at(step_index));
            task = Json::array({board.at("id"), board.at("revision"), step_index});
        }
    }
    const char *state = "ack";
    if (refused)
        state = "refused";
    else if (completed)
        state = (kind == "throw" || kind == "plant") ? "ack" : "completed";
    else if (a.value("blockedTicks", 0) >= 5 || a.at("blind") > now)
        state = "unavailable";
    else if (distance(actor_point(a), goal) <= 8 && kind == "hold" && a.at("visible").empty() &&
             a.at("reloadAt") == 0 && a.at("ammo") > 0) {
        // Report only a short, visible segment in the direction actually held.
        const auto pos = actor_point(a);
        const double heading = a.at("heading");
        Point look{pos[0] + 14 * std::cos(heading), pos[1] + 14 * std::sin(heading), pos[2]};
        bool clear_lane = grid ? grid->clear(xy(a), {look[0], look[1]})
                               : !arena.objectives().map().hit(pos, look, 1, 64, 64);
        if (clear_lane && std::ranges::none_of(w.at("effects"), [&](const Json &f) {
                return f.at("kind") == "Дым" && f.at("land") <= now && now < f.at("end") &&
                       near_segment(pos, look, actor_point(f), f.at("radius"));
            })) {
            state = "ready";
            goal = look;
        }
    }
    announce(*this, "order", state, goal, task);
}

const Json *AgentTurn::peer_request(int &benefit) const {
    auto calls = a.find("peerCalls");
    if (calls == a.end() || a.at("blind") > now)
        return nullptr;
    const Json *best = nullptr;
    for (const auto &call : *calls) {
        const auto &state = call.at("state");
        if (state != "help" && state != "check" && state != "refused" && state != "unavailable")
            continue;
        auto age = now - call.at("tick").get<Tick>();
        if (age < 0 || age >= 25)
            continue;
        const auto point = call.at("point").get<Point>();
        const double range = distance(actor_point(a), call.at("origin").get<Point>());
        if (range > 75)
            continue;
        if (std::ranges::none_of(squad, [&](auto mate) { return mate->at("id") == call.at("sender"); }))
            continue;
        int score = (state == "help" ? 72 : 59) + call.at("quality").get<int>() / 5 +
                    skills.at("support").get<int>() / 10 - int(age) * 2 - int(range / 3);
        for (const auto &other : *calls) {
            if (other.at("state") == "ready" && now - other.at("tick").get<Tick>() < 18 &&
                distance(point, other.at("point").get<Point>()) < 14)
                score -= 16;
        }
        if (score > benefit) {
            benefit = score;
            best = &call;
        }
    }
    return best;
}
}
