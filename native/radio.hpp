#pragma once
#include "team_ai.hpp"

namespace esport {
bool peer_radio(const Json &world);
void report_contact(Json &world, Json &actor, const Json &sight);
int reception_quality(const Json &world, const Json &sender, const Json &recipient);
// Updates disputed evidence in place even when the earlier estimate wins.
bool accept_report(Json &incoming, Json *prior, const std::string &sender, int quality, Tick now);
}
