#pragma once
#include <array>
#include <cstddef>

namespace esport {
// This policy receives observations and personal resources. It cannot query a
// match or a map.
enum class Choice { assignment, engage, cover, watch, reload, objective, escape, count };
struct Situation {
    int contacts, hp, ammo, magazine, reserve, reload_ticks, time_left, interaction_left;
    int aggression, risk, discipline, reading, familiarity, role_experience;
    bool entry, support, committed, carrying, can_escape, remembered, recent_damage;
    int reload_exposure; // Personal experience of taking fire while reloading at
                         // this position.
    int confidence;      // 0..100, after distance, source and age of the strongest
                         // local report
};
// Observable conditions for the second policy revision. No world or roster
// references.
struct ExecutionContext {
    Choice incumbent = Choice::count;
    int other_contacts{}, proximity{}, crossfire{}, incoming_damage{}, shots_needed{}, gained_rounds{};
    int reload_duration{}, objective_ticks{}, bullets_per_reload{}, route_cost{};
    bool can_draw_loaded_gun{}, unsafe_reload_window{}, exposed_lane{}, under_fire{};
    bool changed{}, advancing{}, finishing_cover{}, continuing_reload{}, protected_cover{}, tracking{};
    bool route_available = true;
};
struct Option {
    Choice choice;
    int benefit, risk;
    bool available;
    bool reachable = true;
    int continuity{};
    int value() const { return benefit - risk + continuity; }
};
using Options = std::array<Option, static_cast<std::size_t>(Choice::count)>;
Options alternatives(const Situation &s, const ExecutionContext *execution = nullptr);
} // namespace esport
