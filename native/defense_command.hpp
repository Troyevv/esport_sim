#pragma once
#include "team_ai.hpp"
namespace esport {
void assign_reserves(const OpeningMap &arena, Json &plan, const Squad &squad, Json destination,
                     const Pressure &counts, Tick now, const Json &bomb_site);
void commit_reserves(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &site);
void review_opening(const OpeningMap &arena, Json &plan, const Squad &squad, Tick now, const Json &captain);
void brief_defense(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &leader,
                   const Json &player, Tick now, const std::string &map);
} // namespace esport
