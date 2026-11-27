#pragma once
#include <array>
#include <cstddef>

namespace esport {
// This policy receives observations and personal resources. It cannot query a match or a map.
enum class Choice { assignment, engage, cover, watch, reload, objective, escape, count };
struct Situation {
    int contacts, hp, ammo, magazine, reserve, reload_ticks, time_left, interaction_left;
    int aggression, risk, discipline, reading, familiarity, role_experience;
    bool entry, support, committed, carrying, can_escape, remembered, recent_damage;
    int reload_exposure; // Personal experience of taking fire while reloading at this position.
    int confidence;      // 0..100, after distance, source and age of the strongest local report
};
struct Option {
    Choice choice;
    int benefit, risk;
    bool available;
    bool reachable = true;
    int value() const { return benefit - risk; }
};
using Options = std::array<Option, static_cast<std::size_t>(Choice::count)>;
Options alternatives(const Situation &s);
} // namespace esport
