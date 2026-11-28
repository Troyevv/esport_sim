#include "tick_output.hpp"
#include "team_ai.hpp"
#include <set>
namespace esport {
namespace {
Json preview_frame(const Json &roster) {
    auto frame = Json::array();
    for (const auto &a : roster) {
        auto pose = Json::array({a.at("x"), a.at("y"), a.at("heading"), a.at("hp")});
        if (a.contains("z"))
            pose.push_back(a.at("z"));
        frame.push_back(std::move(pose));
    }
    return frame;
}
Json motion_sample(const Json &roster) {
    std::map<std::string, std::set<std::string>> visible{{"T", {}}, {"CT", {}}};
    for (auto &a : roster)
        for (auto &id : a.at("visible"))
            visible.at(a.at("team")).insert(id.get<std::string>());
    auto frame = Json::object();
    for (auto &a : roster) {
        auto id = a.at("id").get<std::string>();
        auto teams = Json::array();
        for (auto side : {"T", "CT"})
            if (a.at("team") == side || visible.at(side).contains(id))
                teams.push_back(side);
        auto pose = Json::array({a.at("x"), a.at("y"), a.at("heading")});
        if (a.contains("z"))
            pose.push_back(a.at("z"));
        frame[id] = Json::array({std::move(pose), std::move(teams)});
    }
    return frame;
}
// Diagnostic boundary only. Coordinates and private inboxes never feed back into the match.
Json review_frame(const Json &w, const OpeningMap *arena) {
    auto tick = w.at("tick").get<Tick>();
    Json frame = {{"tick", tick}, {"round", w.at("round")}, {"phase", w.at("phase")}};
    if (w.at("phase") != "live" && w.at("phase") != "planted")
        return frame;
    Json packets = Json::array();
    for (const auto &m : w.at("messages")) {
        if (!m.contains("sight"))
            continue;
        const auto &r = m.at("sight");
        if (r.at("tick") == tick && r.at("source") == "Зрение")
            packets.push_back({m.at("team"), m.at("sender"), r.at("id"), r.at("x"), r.at("y"), r.at("z"),
                               m.at("due"), r.value("carryingC4", false), r.value("groupSize", 1)});
    }
    if (!packets.empty())
        frame["sent"] = std::move(packets);
    if (tick % 5)
        return frame;
    Json actors = Json::array();
    for (const auto &a : w.at("agents")) {
        if (!a.contains("decision") || a.at("hp") == 0)
            continue;
        const auto side = a.at("team").get<std::string>(), id = a.at("id").get<std::string>();
        const auto &p = w.at("plans").at(side);
        const auto &decision = a.at("decision");
        const auto &m = a.at("mind");
        const auto &dest = a.at("dest");
        Json goal = nullptr;
        if (dest.size() >= 4 && !dest[0].is_null())
            goal = {dest[1], dest[2], dest[3]};
        const auto *reserve = side == "CT" ? relief(p, a) : nullptr;
        Json duty = nullptr;
        if (reserve)
            duty = {reserve->value("site", std::string{}), reserve->value("issued", Tick{-1}),
                    reserve->value("hold", Json(nullptr)), reserve->value("acknowledged", std::string{})};
        Json group = nullptr;
        if (a.contains("groupDuty") && a.at("groupDuty").is_object()) {
            const auto &g = a.at("groupDuty");
            group = {g.at("ticket").at(0), g.value("until", Tick{-1}), g.value("state", std::string{}),
                     g.value("angle", Json(nullptr)), g.value("worked", Tick{-1})};
        }
        Json expected = nullptr, partner = nullptr;
        if (side == "T" && p.contains("commandJobs") && p.at("commandJobs").contains(id))
            expected = p.at("commandJobs").at(id).at("point");
        else if (reserve && reserve->contains("hold"))
            expected = reserve->at("hold");
        if (side == "CT" && w.at("phase") == "live" && p.contains("opening") && p.at("opening").is_object()) {
            const auto &job = p.at("opening").at("jobs").at(id);
            partner = job.value("partner", Json(nullptr));
        }
        if (side == "CT" && w.at("phase") == "planted" && p.contains("retake") &&
            p.at("retake").contains("duties") && p.at("retake").at("duties").contains(id))
            partner = p.at("retake").at("duties").at(id).value("partner", Json(nullptr));
        const auto &slot = p.at("orders").at("slots").at(a.at("slot").get<int>());
        if (expected.is_null() && side == "CT")
            expected = slot.value("hold", Json(nullptr));
        const auto &path = a.at("path");
        Json next = path.empty() ? Json(nullptr) : path.front();
        actors.push_back({id,
                          side,
                          a.at("x"),
                          a.at("y"),
                          a.at("z"),
                          a.at("status"),
                          decision.at("intent"),
                          a.at("visible").size(),
                          a.at("reloadAt"),
                          a.value("blockedTicks", 0),
                          a.at("heading"),
                          m.at("stress"),
                          m.at("confidence"),
                          m.at("frustration"),
                          m.at("focus"),
                          goal,
                          duty,
                          group,
                          a.value("waypoint", 0),
                          a.at("blind"),
                          a.at("lastShot"),
                          decision.at("task"),
                          expected,
                          partner,
                          a.value("heardSite", Json(nullptr)),
                          next,
                          a.value("routeIssued", Tick{-1}),
                          slot.value("watch", Json(nullptr))});
        if (a.at("id") == p.at("captain")) {
            Json known = Json::array();
            for (const auto &r : a.at("knowledge")) {
                if (tick - r.at("tick").get<Tick>() > 45 ||
                    (r.at("source") != "Радио" && r.at("source") != "Зрение"))
                    continue;
                bool approach = false;
                const auto site = arena ? site_for(*arena, actor_point(r), approach) : std::nullopt;
                known.push_back({r.at("id"), r.at("tick"), r.at("x"), r.at("y"), r.at("z"), r.at("source"),
                                 r.value("carryingC4", false), r.value("reporter", std::string{}),
                                 site.value_or(""), approach});
            }
            frame[side] = {
                {"captain", id},
                {"known", std::move(known)},
                {"site", p.at("site")},
                {"choice", side == "CT" && p.contains("defenseCall") && p.at("defenseCall").contains("kind")
                               ? p.at("defenseCall").at("kind").get<std::string>()
                               : p.value("commandKind", std::string{})},
                {"issued", p.value("issued", Tick{-1})},
                {"revision", p.value("revision", 0)}};
            if (side == "CT" && p.contains("defenseCall") && p.at("defenseCall").contains("site")) {
                frame[side]["site"] = p.at("defenseCall").at("site");
                frame[side]["issued"] = p.at("defenseCall").at("issued");
            }
            if (side == "CT" && p.contains("defenseScores"))
                frame[side]["scores"] = p.at("defenseScores");
            if (side == "T" && p.contains("assessment"))
                frame[side]["scores"] = p.at("assessment").value("scores", Json::object());
        }
    }
    frame["actors"] = std::move(actors);
    return frame;
}
} // namespace
void TickSamples::before(const Json &world) {
    if (mode == TickOutput::Profile)
        start = std::chrono::steady_clock::now();
    else if (mode == TickOutput::Motion)
        samples.push_back(motion_sample(world.at("agents")));
    else if (mode == TickOutput::Preview)
        samples.push_back(preview_frame(world.at("agents")));
}
bool TickSamples::end_of_preview(const Json &world) const {
    return mode == TickOutput::Preview && world.at("phase") == "result";
}
void TickSamples::after(const Json &world, const OpeningMap *arena) {
    if (mode == TickOutput::Review) {
        auto frame = review_frame(world, arena);
        if (!actions.empty())
            frame["actions"] = std::exchange(actions, Json(nullptr));
        if (frame.contains("sent") || frame.contains("actors") || world.at("tick").get<Tick>() % 50 == 0)
            samples.push_back(std::move(frame));
        return;
    }
    if (mode == TickOutput::Individual || mode == TickOutput::Group) {
        Json actors = Json::array();
        for (const auto &a : world.at("agents")) {
            auto decision = a.find("decision");
            if (decision == a.end() || (a.at("hp") == 0 && a.at("lastHurt") != world.at("tick")))
                continue;
            auto cover = a.find("shelter");
            actors.push_back(Json::array({a.at("id"),
                                          a.at("team"),
                                          decision->at("intent"),
                                          a.at("x"),
                                          a.at("y"),
                                          a.value("z", 0.),
                                          a.at("hp"),
                                          a.at("armor"),
                                          a.at("ammo"),
                                          a.at("reserve"),
                                          a.at("reloadAt"),
                                          a.at("weapon"),
                                          a.at("visible").size(),
                                          a.at("lastHurt"),
                                          a.at("lastShot"),
                                          cover == a.end() ? Json(nullptr) : *cover,
                                          a.value("stepIndex", -1),
                                          a.at("status"),
                                          a.at("heading"),
                                          a.value("blockedTicks", 0)}));
            if (mode == TickOutput::Group) {
                Json lead = nullptr, duty = nullptr;
                if (a.contains("groupLead")) {
                    const auto &g = a.at("groupLead");
                    if (g.at("worked") == world.at("tick"))
                        lead = Json::array({g.at("ticket"), g.value("mate", Json(nullptr)), g.at("until")});
                } else if (a.contains("sentFeedback") && a.at("sentFeedback").contains("stage")) {
                    const auto &g = a.at("sentFeedback").at("stage");
                    lead = Json::array({Json::array({a.at("id"), "stage", g.at("tick")}), nullptr,
                                        g.at("tick").get<Tick>() + 18});
                }
                if (a.contains("groupDuty")) {
                    const auto &g = a.at("groupDuty");
                    duty = Json::array({g.at("ticket"), g.at("state"), g.at("wing")});
                }
                actors.back().push_back(Json::array({std::move(lead), std::move(duty)}));
            }
        }
        samples.push_back(
            Json::array({world.at("tick"), world.at("round"), world.at("phase"), std::move(actors)}));
        return;
    }
    if (mode != TickOutput::Profile)
        return;
    timings.push_back(
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start)
            .count());
    if (world.at("tick").get<Tick>() % 10 == 0) {
        auto pose = Json::array();
        for (auto &a : world.at("agents"))
            pose.push_back(Json::array({a.at("id"), a.at("x"), a.at("y"), a.value("z", Json(nullptr)),
                                        a.at("hp"), a.value("navArea", Json(nullptr))}));
        samples.push_back(std::move(pose));
    }
}
Json TickSamples::finish(const Json &world) {
    if (mode == TickOutput::Preview)
        samples.push_back(preview_frame(world.at("agents")));
    if (mode == TickOutput::Profile)
        return Json{{"samples", std::move(samples)},
                    {"durations", std::move(timings)},
                    {"tick", world.at("tick")},
                    {"phase", world.at("phase")}};
    return std::move(samples);
}
} // namespace esport
