#pragma once
#include "team_ai.hpp"
namespace esport {
std::string grid_buy(const Json &w, const Json &cfg, const std::string &side, const Json &call);
void grid_purchase(Json &w, const Json &cfg, const std::string &side, const std::string &buy, Json &captain);
void grid_observe(Json &w, const GridMap &grid);
void grid_review(Json &w, const Squad &squad, const GridMap &grid);
int equipment_value(const Json &a, const Json &cfg);
} // namespace esport
