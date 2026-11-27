#pragma once
#include "team_ai.hpp"
namespace esport {
using Losses = std::map<std::string, std::vector<Tick>>;
void compare_defense(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                     const Json &leader, const Reports &reports, const Pressure &pressure,
                     const Losses &losses, const Json &bomb, const Json &on_site);
void assign_reserves(const OpeningMap &arena, Json &plan, const Squad &squad, Json destination,
                     const Pressure &counts, Tick now, const Json &bomb_site, int limit = -1);
void commit_reserves(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &site);
void review_opening(const OpeningMap &arena, Json &plan, const Squad &squad, Tick now, const Json &captain);
void brief_defense(const OpeningMap &arena, Json &plan, const Squad &squad, const Json &leader,
                   const Json &player, Tick now, const std::string &map, bool peers);
} // namespace esport
