#pragma once
#include "team_ai.hpp"

namespace esport {
// Only model 12 owns transient affect. Older active checkpoints keep their policy.
void initialize_mind(const Json &world, Json &actor);
void encounter_emotion(Json &world, Json &actor, bool success, bool mistake, Tick event,
                       const std::string &weapon);
void self_flash_emotion(Json &world, Json &actor, Tick event);
void round_emotion(Json &world, Json &actor, bool won, int target, Tick round_event, bool overtime);
void timeout_recovery(Json &world, const Json &team);
void spend_talk_time(Json &world, int seconds);
void coach_address(Json &world, const Json &team, const Json &request);
void finish_ai_break(Json &world, Tick now);
int break_seconds(const Json &world, const Json &rules);
void consider_break(Json &world, const Json &rules);
int repeat_cost(int elapsed, int prior, int current, bool won, int stakes);
int timeout_need(int distress, int mistakes, int deficit, int recent_losses, int economic_gap, int stakes,
                 int rounds_left, int remaining, int quality);
} // namespace esport
