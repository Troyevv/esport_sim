#pragma once
#include "opening.hpp"

namespace esport {
using Squad = std::vector<Json *>;
using Reports = std::vector<const Json *>;
using Pressure = std::map<std::string, double>;
Point actor_point(const Json &p);
int chemistry(const Json &w, const Json &l, const Json &r);
const Json &player_profile(const Json &w, const Json &actor);
void captain_review(Json &w, const Json &cfg, const OpeningMap &arena, const std::string &side);
void direct_defense(Json &w, const OpeningMap &arena, Json &plan, const Squad &squad, Json &captain);
void assemble_retake(Json &w, const Json &cfg, const OpeningMap &arena, const Squad &squad,
                     const Json &captain, const std::string &site);
void review_attack(Json &w, const Json &cfg, const OpeningMap &arena, Json &plan, const Squad &squad,
                   const Json &captain, const Reports &reports);
Pressure site_pressure(const OpeningMap &arena, const Reports &reports, Tick now);
void sector_pressure(const OpeningMap &arena, const Reports &reports, const Reports &calls, Tick now,
                     Pressure &counts);
const Json *relief(const Json &plan, const Json &a);
const Json &assignment(const Json &plan, const Json &a, const Squad &squad);
} // namespace esport
