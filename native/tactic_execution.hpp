#pragma once
#include "objectives.hpp"

namespace esport {
// Returns [kind, target] or null when the scripted steps have finished.
// Called after normal contact, rescue and reinforcement decisions.
Json board_step(Json &w, Json &actor, const Json &cfg, const Objectives &objectives, const Json &known_device,
                const std::vector<Hazard> &fire);
double move_speed(const Json &player);
bool travel(Json &actor, const Json &player, const PhysicalNavigation &map, const Point &goal, double pace,
            const std::vector<Hazard> &fire, Tick now);
} // namespace esport
