#pragma once
#include "agent_helpers.hpp"

namespace esport {
// Time lost on a NAV route according to one recipient's current observations.
double route_resistance(const Json &world, const Json &cfg, const PhysicalNavigation &nav,
                        const Json &observer, Point start, const WalkPath &route, double speed);
}
