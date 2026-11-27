#include "tick_output.hpp"
#include <set>
namespace esport {
namespace {
Json preview_frame(const Json &roster) {
    auto frame = Json::array();
    for (const auto &a : roster)
        frame.push_back(Json::array({a.at("x"), a.at("y"), a.at("heading"), a.at("hp"), a.at("z")}));
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
        frame[id] = Json::array({Json::array({a.at("x"), a.at("y"), a.at("heading"), a.at("z")}), teams});
    }
    return frame;
}
} // namespace
void TickSamples::before(const Json &world) {
    if (mode == TickOutput::Profile)
        start = std::chrono::steady_clock::now();
    else if (mode == TickOutput::Motion)
        samples.push_back(motion_sample(world.at("agents")));
    else
        samples.push_back(preview_frame(world.at("agents")));
}
bool TickSamples::end_of_preview(const Json &world) const {
    return mode == TickOutput::Preview && world.at("phase") == "result";
}
void TickSamples::after(const Json &world) {
    if (mode != TickOutput::Profile)
        return;
    timings.push_back(
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start)
            .count());
    if (world.at("tick").get<Tick>() % 10 == 0) {
        auto pose = Json::array();
        for (auto &a : world.at("agents"))
            pose.push_back(
                Json::array({a.at("id"), a.at("x"), a.at("y"), a.at("z"), a.at("hp"), a.at("navArea")}));
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
