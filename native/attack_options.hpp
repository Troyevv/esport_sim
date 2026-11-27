#pragma once
#include "team_ai.hpp"

namespace esport {
double travel_ticks(const OpeningMap &arena, const std::string &site, AreaId area);
void resume_routes(const OpeningMap &arena, Json &plan, const Squad &squad);
using SectorCounts = std::map<std::string, int>;
void compare_attack(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                    const Json &captain, const Json *carrier, const Reports &reports, const Pressure &pressure,
                    SectorCounts &held, SectorCounts &blocked, bool probing);
} // namespace esport
