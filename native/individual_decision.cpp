#include "individual_decision.hpp"
#include <algorithm>

namespace esport {
Options alternatives(const Situation &s) {
    const bool contact = s.contacts > 0;
    const int exposure = std::min(3, s.contacts) * 12 + (100 - s.hp) / 3 + (s.recent_damage ? 12 : 0);
    const int urgency = (s.committed ? 18 : 0) + (s.carrying ? 12 : 0) + (s.time_left < 75 ? 40 : 0);
    const int ammunition = s.ammo * 100 / std::max(1, s.magazine);
    const int sustain = std::min(25, s.ammo * 5);
    Options options{
        {{Choice::assignment, 48 + urgency + s.discipline / 10, exposure, !contact && s.interaction_left < 0},
         {Choice::engage, 60 + sustain + s.aggression / 5 + (s.entry ? 8 : 0),
          exposure * (150 - s.risk) / 150 + (s.reload_ticks ? 35 : 0), contact},
         {Choice::cover, 16 + exposure + s.reading / 8 + s.familiarity / 12 + (s.reload_ticks ? 30 : 0),
          s.aggression / 6 + urgency / 3, contact && s.interaction_left < 0},
         {Choice::watch, 22 + s.confidence / 3 + s.role_experience / 9 + (s.support ? 6 : 0),
          urgency + (s.entry ? 8 : 0), !contact && s.remembered && s.interaction_left < 0},
         {Choice::reload, 100 - ammunition + s.discipline / 12,
          s.confidence / 2 + urgency + s.reload_exposure + (s.recent_damage ? 30 : 0),
          !contact && !s.reload_ticks && s.reserve > 0 && ammunition < 55 && s.interaction_left < 0},
         {Choice::objective, 120 - std::min(55, std::max(0, s.interaction_left)), contact ? exposure / 2 : 0,
          s.interaction_left >= 0},
         {Choice::escape, 160, exposure / 3, s.can_escape && s.interaction_left < 0}}};
    // The enum order resolves equal scores deterministically. Comparing candidates neither consumes RNG nor
    // executes moves.
    std::sort(options.begin(), options.end(), [](const Option &a, const Option &b) {
        if (a.available != b.available)
            return a.available;
        if (a.value() != b.value())
            return a.value() > b.value();
        return a.choice < b.choice;
    });
    return options;
}
} // namespace esport
