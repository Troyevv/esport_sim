#pragma once
#include "agent_helpers.hpp"

namespace esport {
inline Json group_ticket(const Json &offer) {
    return Json::array({offer.at("sender"), offer.at("channel"), offer.at("tick")});
}
inline std::string reply_channel(const Json &ticket) {
    return "reply/" + ticket.at(0).get<std::string>() + "/" + ticket.at(1).get<std::string>();
}
inline bool terminal_reply(const Json &state) {
    return state == "decline" || state == "cancel" || state == "complete";
}
inline int radio_delay(const AgentTurn &t) {
    return 1 + (100 - t.skills.at("communication").get<int>()) / 12;
}
// A different nominee may have confirmed cover while the thrower's radio packet
// was in transit.
inline bool waiting_for_ticket_flash(const AgentTurn &t, const Json &ticket) {
    auto warnings = t.a.find("flashWarnings");
    return warnings != t.a.end() && std::ranges::any_of(*warnings, [&](const Json &warning) {
               return warning.at("land") > t.now && warning.value("ticket", Json(nullptr)) == ticket;
           });
}
inline bool can_support(const AgentTurn &t) {
    return t.a.at("blind") <= t.now && t.a.at("reloadAt") == 0 && t.a.at("ammo") > 0 &&
           t.a.at("ready") <= t.now && t.a.at("visible").empty();
}
inline Json *living_mate(const AgentTurn &t, const Json &id) {
    for (auto m : t.squad)
        if (m->at("id") == id)
            return m;
    return nullptr;
}
} // namespace esport
