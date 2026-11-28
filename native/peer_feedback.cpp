#include "grenades.hpp"
#include "agent_helpers.hpp"
#include "radio.hpp"
#include "group_tasks.hpp"

namespace esport {
namespace {
void announce(AgentTurn &turn, const char *channel, const char *state, const Point &point, Json order, bool advancing = false) {
    auto &a = turn.a;
    auto &last = a["sentFeedback"][channel];
    const bool urgent = std::string_view(state) == "refused" || std::string_view(state) == "completed";
    if (!last.is_null()) {
        auto age = turn.now - last.at("tick").get<Tick>();
        if (!urgent && age < 6)
            return;
        const bool changed_load = small_groups(turn.w) && std::string_view(channel) == "order" &&
            (last.value("armed", false) != (a.at("ammo") > 0 && a.at("reloadAt") == 0 && a.at("blind") <= turn.now) ||
             last.value("hasUtility", false) != !a.at("utility").empty());
        const bool motion_changed = turn.w.value("agentPolicy",0)>=12 && std::string_view(channel)=="order" && last.value("advancing",false)!=advancing;
        if (!motion_changed && !changed_load && last.at("state") == state && last.at("order") == order && last.value("waypoint", 0) == a.value("waypoint", 0) &&
            distance(last.at("point").get<Point>(), point) < 10 &&
            (age < 30 || std::string_view(state) == "ack"))
            return;
    }
    last = {{"state", state}, {"order", std::move(order)}, {"point", point}, {"origin", actor_point(a)},
            {"tick", turn.now}, {"channel", channel}, {"waypoint", a.value("waypoint", 0)}};
    if (std::string_view(state) == "refused")
        last["reason"] = a.at("lastRefusal").at("reason");
    if (small_groups(turn.w)) {
        if (last.at("channel") == "contact" || last.at("state") == "refused" || last.at("state") == "unavailable")
        {
            if (group_tasks(turn.w)) {
                auto until = turn.offer_deadline(last.at("state") == "help");
                last["until"] = until;
                last["phase"] = turn.w.at("phase");
                last["members"] = turn.nominate_group(actor_point(a), point, until);
            } else
                last["members"] = turn.group_members(actor_point(a));
        }
        if (last.at("channel") == "order") {
            if (turn.w.value("agentPolicy",0)>=12) last["advancing"] = advancing;
            last["armed"] = a.at("ammo") > 0 && a.at("reloadAt") == 0 && a.at("blind") <= turn.now;
            last["hasUtility"] = !a.at("utility").empty();
        }
    }
    const int skill = turn.skills.at("communication");
    turn.w.at("messages").push_back({{"team", turn.side}, {"sender", a.at("id")}, {"feedback", last},
                                     {"due", plus_ticks(turn.now, 1 + (100 - skill) / 12)}});
}
}

void AgentTurn::peer_feedback(const std::string &kind) {
    if (!grid && side == "T" && collective_attack(w) && active(plan, "probe") &&
        !active(plan.at("probe"), "released") && a.contains("sentFeedback")) {
        const auto &sent = a.at("sentFeedback");
        if (sent.contains("sector") && sent.at("sector").at("state") == "held") {
            const Json last = sent.at("sector");
            if (distance(actor_point(a), last.at("point")) > 6 || !a.at("visible").empty() || a.at("blind") > now)
                signal_group("sector", "lost", actor_point(a), last.at("order"));
        }
    }
    if (small_groups(w) && !grid && side == "CT" && w.at("phase") == "live" && active(plan, "opening")) {
        const auto &job = plan.at("opening").at("jobs").at(a.at("id").get<std::string>());
        if (active(job, "partner") && job.contains("gate")) {
            const auto pos = actor_point(a);
            const double h = a.at("heading");
            Point look{pos[0] + 8 * std::cos(h), pos[1] + 8 * std::sin(h), pos[2]};
            bool at_gate = distance(pos, job.at("gate").get<Point>()) < 5 && !active(job, "withdrawn") &&
                           a.at("visible").empty() && (kind == "move" || kind == "hold") && group_lane(look);
            const bool preparing = active(job, "throw") && !job.at("throw").contains("skip") &&
                                   now < job.at("throw").value("land", now + 1);
            at_gate &= !preparing || job.at("role") != "страховка";
            const auto &sent = a["sentFeedback"];
            if (at_gate || (sent.contains("gate") && sent.at("gate").at("state") == "set"))
                signal_group("gate", at_gate ? "set" : "left", look, job.at("zone"));
        }
    }
    // A nominee who loses the angle, ammunition or route releases the other
    // member through the same delayed channel as the original confirmation.
    if (group_tasks(w))
        finish_group_tasks();
    else if (small_groups(w) && a.contains("peerCalls")) {
        for (const auto &call : a.at("peerCalls")) {
            if (!call.contains("members") || call.at("members").empty() ||
                call.at("members").front() != a.at("id") || now - call.at("tick").get<Tick>() >= 25)
                continue;
            const Json task = Json::array({call.at("sender"), call.at("tick")});
            const auto sent = a.find("sentFeedback");
            const bool lost = sent != a.end() && sent->contains("support") &&
                sent->at("support").at("order") == task && sent->at("support").at("state") == "set" &&
                (kind != "hold" || !group_lane(call.at("point").get<Point>()));
            if (lost || a.at("blind") > now || a.at("ammo") == 0 || a.at("reloadAt") > now ||
                a.value("blockedTicks", 0) >= 5) {
                const auto point = call.at("point").get<Point>();
                signal_group("support", "decline", point, task);
                break;
            }
        }
    }
    // A request quotes a firsthand observation only. A received request or
    // a radio contact can never itself trigger another request.
    if (a.value("flashLevel", 0.) >= .55 && now % 4 == slot % 4) {
        Json latest = nullptr;
        for (const auto &r : a.at("knowledge"))
            if (visual(r) && now - r.at("tick").get<Tick>() < 24 &&
                (latest.is_null() || r.at("tick") > latest.at("tick")))
                latest = r;
        announce(*this, "contact", "help", latest.is_null() ? actor_point(a) : actor_point(latest),
                 latest.is_null() ? Json("Прикрытие") : latest.at("id"));
    } else if (now % 4 == slot % 4 && a.at("blind") <= now) {
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
    if (side == "T" && active(plan, "revision") && w.at("phase") == "live") {
        const auto &jobs = plan.at("commandJobs");
        if (auto duty = jobs.find(a.at("id").get<std::string>()); duty != jobs.end())
            goal = duty->at("point");
        task = Json::array({"live", plan.at("site"), goal, plan.at("revision")});
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
                       crosses_volume(f, pos, look);
            })) {
            state = "ready";
            goal = look;
        }
    }
    announce(*this, "order", state, goal, task, kind == "move" && distance(prior_position, actor_point(a)) > .01);
}

const Json *AgentTurn::peer_request(int &benefit) const {
    auto calls = a.find("peerCalls");
    if (calls == a.end() || a.at("blind") > now)
        return nullptr;
    const bool grouped = small_groups(w);
    const Json *best = nullptr;
    for (const auto &call : *calls) {
        const auto &state = call.at("state");
        if (state != "help" && state != "check" && state != "refused" && state != "unavailable" &&
            !(grouped && state == "stage"))
            continue;
        // A fresh contact supersedes this speaker's waypoint invitation even
        // for listeners who were only named in the older invitation.
        if (state == "stage" && call.at("tick") < a.value("routeIssued", Tick{-1}))
            continue;
        if (grouped && state == "stage") {
            auto source = plan.find("routeChanges");
            if (source != plan.end() && call.at("tick") < source->value(call.at("sender").get<std::string>(), Tick{-1}))
                continue;
            auto contact = recent_call(call.at("sender"), "contact", 25);
            if (contact && contact->at("tick") >= call.at("tick"))
                continue;
        }
        if (grouped && state == "help") {
            auto stage = recent_call(call.at("sender"), "stage", 25);
            if (stage && stage->at("tick") > call.at("tick"))
                continue;
        }
        if (grouped && (!call.contains("members") || !member_of(call.at("members"), a.at("id"))))
            continue;
        auto age = now - call.at("tick").get<Tick>();
        const bool tasks = group_tasks(w);
        if (age < 0 || (tasks ? now >= call.value("until", call.at("tick").get<Tick>() + 25) : age >= 25))
            continue;
        const auto point = call.at("point").get<Point>();
        const double range = distance(actor_point(a), call.at("origin").get<Point>());
        if (range > (tasks ? 96 : 75))
            continue;
        if (!grouped && std::ranges::none_of(squad, [&](auto mate) { return mate->at("id") == call.at("sender"); }))
            continue;
        int score = (state == "help" ? 72 : 59) + call.at("quality").get<int>() / 5 +
                    skills.at("support").get<int>() / 10 - int(age) * 2 - int(range / 3);
        if (grouped && state == "stage")
            score += 12;
        for (const auto &other : *calls) {
            if (other.at("state") == "ready" && now - other.at("tick").get<Tick>() < 18 &&
                distance(point, other.at("point").get<Point>()) < 14)
                score -= 16;
        }
        if (tasks) {
            if (call.value("phase", w.at("phase")) != w.at("phase"))
                continue;
            auto ticket = group_ticket(call);
            auto sent = a.find("sentFeedback");
            auto channel = reply_channel(ticket);
            if (sent != a.end() && sent->contains(channel)) {
                const auto &reply = sent->at(channel);
                if (reply.at("order") == ticket && terminal_reply(reply.at("state")))
                    continue;
            }
            auto release = recent_call(call.at("sender"), "launch", 45);
            if (release && release->at("order") == ticket && terminal_reply(release->at("state")))
                continue;
            const bool incumbent = active(a, "groupDuty") && a.at("groupDuty").at("ticket") == ticket;
            if (incumbent)
                score += state == "stage" ? 22 + int(age) : 16;
            if (state == "help")
                score += 10;
            if (active(plan, "board") || (!device.empty() && device.value("carrier", Json(nullptr)) == a.at("id")))
                score -= 18;
            if (active(a, "groupLead") && !a.at("groupLead").value("closed", false) && state != "help")
                continue;
            if (score == benefit && best && ticket < group_ticket(*best))
                best = &call;
        }
        if (score > benefit) {
            benefit = score;
            best = &call;
        }
    }
    return best;
}
}
