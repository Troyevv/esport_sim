#pragma once
#include "round_rules.hpp"
#include <chrono>

namespace esport {
class OpeningMap;
enum class TickOutput { Motion, Preview, Profile, Individual, Group, Review };

// Collect only the requested boundary DTOs as a batch. The simulation never
// calls into a renderer, timer service or Python observer.
class TickSamples {
  public:
    explicit TickSamples(TickOutput mode) : mode(mode) {}
    void before(const Json &world);
    void after(const Json &world, const OpeningMap *arena);
    bool traces_actions(Tick tick) const { return mode == TickOutput::Review && tick % 5 == 0; }
    Json actions;
    bool end_of_preview(const Json &world) const;
    Json finish(const Json &world);

  private:
    TickOutput mode;
    Json samples = Json::array(), timings = Json::array();
    std::chrono::steady_clock::time_point start;
};
} // namespace esport
