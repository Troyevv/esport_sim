#pragma once
#include "team_ai.hpp"

namespace esport {
// Only model 12 owns transient affect. Older active checkpoints keep their policy.
void initialize_mind(const Json &world, Json &actor);
void encounter_emotion(Json &world, Json &actor, bool success, bool mistake, Tick event);
void round_emotion(Json &world, Json &actor, bool won, int target, Tick round_event);
void timeout_recovery(Json &world, const Json &team);
void coach_address(Json &world, const Json &team, const Json &request);
void consider_break(Json &world);
int timeout_need(int distress, int mistakes, int deficit, int recent_losses, int economic_gap, int stakes,
                 int round, int remaining, int quality);
} // namespace esport
