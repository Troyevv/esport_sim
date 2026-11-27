#pragma once
#include <nlohmann/json.hpp>
#include <string>

namespace esport {
using Json = nlohmann::ordered_json;
using Tick = std::int64_t;
std::uint32_t draw_rng(Json &actor);
Tick plus_ticks(Tick tick, Tick offset);
Json &emit(Json &state, const std::string &kind, const std::string &text, Json side = nullptr);
void pay(Json &w, Json &a, int delta, const std::string &reason, int cap);
void start_round(Json &state, const Json &cfg, const Json &spawns);
void settle_round(Json &state, const Json &config, const std::string &side, const std::string &reason);
} // namespace esport
