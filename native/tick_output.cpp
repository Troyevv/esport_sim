#include "tick_output.hpp"
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
void TickSamples::after(const Json &world) {
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
                        lead = Json::array({g.at("ticket"), g.value("mate",Json(nullptr)), g.at("until")});
                } else if (a.contains("sentFeedback") && a.at("sentFeedback").contains("stage")) {
                    const auto &g = a.at("sentFeedback").at("stage");
                    lead = Json::array({Json::array({a.at("id"), "stage", g.at("tick")}), nullptr, g.at("tick").get<Tick>()+18});
                }
                if (a.contains("groupDuty")) {
                    const auto &g = a.at("groupDuty");
                    duty = Json::array({g.at("ticket"),g.at("state"),g.at("wing")});
                }
                actors.back().push_back(Json::array({std::move(lead),std::move(duty)}));
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
