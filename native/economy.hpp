#pragma once
#include "round_rules.hpp"
namespace esport {
void equip_weapon(Json &actor,const Json &item,const Json &cfg);
Json grenade_needs(const Json& w,const Json& cfg,const Json& actor,const std::string& site,const Json& board);
Json buy_decision(const Json &w, const Json &config, const std::string &side, const Json &call,
                  const Json &site, const Json &board, const Json &requested);
void buy_equipment(Json &w, const Json &config, const std::string &side, const Json &strategy,
                   const Json &board);
} // namespace esport
