#include "individual_decision.hpp"
#include <algorithm>

namespace esport {
namespace {
void assess_execution(Options &options, const Situation &s, const ExecutionContext &x) {
    auto option = [&](Choice choice) -> Option & { return options[static_cast<size_t>(choice)]; };
    auto &fight = option(Choice::engage), &cover = option(Choice::cover);
    const int danger = x.other_contacts + x.crossfire + x.incoming_damage;
    fight.risk += danger * (120 - s.risk) / 140;
    fight.benefit += std::clamp(s.ammo - x.shots_needed, -6, 4);
    cover.benefit += danger * (45 + s.reading) / 120 + x.proximity / 12;
    cover.risk += x.route_cost;
    if (x.objective_ticks && s.time_left <= x.objective_ticks + 12 && s.ammo && !s.reload_ticks)
        cover.risk += x.objective_ticks; // A detour would consume the remaining plant/defuse window.
    cover.available = (cover.available || x.finishing_cover || x.protected_cover) && x.route_available &&
                      s.interaction_left < 0;
    if (x.finishing_cover || x.protected_cover) {
        // Exposure disappears behind the first corner, before the retreat is
        // complete.
        cover.benefit += (x.finishing_cover ? 32 : 20) + s.confidence / 3;
    }
    if (x.tracking) {
        fight.available = true;
        fight.benefit = 68 + s.confidence / 3;
        fight.risk = 0;
    }

    auto &reload = option(Choice::reload);
    const bool time_to_finish =
        s.time_left > (x.continuing_reload ? s.reload_ticks : x.reload_duration) + x.objective_ticks;
    // Estimate expenditure in the next contact from the actual gun. A half-full
    // Negev and a Glock with two rounds left present different reasons to expose
    // the magazine.
    const int useful_load = std::min(s.magazine, x.shots_needed + x.bullets_per_reload);
    if (!x.continuing_reload) {
        reload.available = reload.available && time_to_finish && !x.under_fire && !x.unsafe_reload_window &&
                           s.ammo < useful_load;
        reload.benefit -= std::max(0, s.ammo - x.shots_needed) * 3;
        reload.benefit -= std::max(0, x.shots_needed - x.gained_rounds) * 6;
        reload.risk += (x.exposed_lane ? (x.proximity + s.confidence) / 3 : 0) +
                       (x.advancing ? x.reload_duration / 3 : 0);
    } else {
        reload.available = !s.contacts && !x.under_fire && time_to_finish && s.interaction_left < 0;
        reload.benefit = 85 + (x.reload_duration - s.reload_ticks);
        reload.risk = x.exposed_lane ? x.proximity / 3 : 0;
    }
    if (x.under_fire || x.changed)
        return;
    if (x.incumbent == Choice::assignment && x.advancing)
        option(Choice::assignment).continuity = 4 + s.discipline / 18;
    if (x.incumbent == Choice::watch && s.confidence >= 25)
        option(Choice::watch).continuity = 3 + s.role_experience / 20;
    if (x.incumbent == Choice::engage && s.ammo && !s.reload_ticks)
        fight.continuity = 5;
    if (x.finishing_cover)
        cover.continuity = 8;
}
} // namespace

Options alternatives(const Situation &s, const ExecutionContext *execution) {
    const bool contact = s.contacts > 0;
    const bool weapon_busy = s.reload_ticks && !(execution && execution->can_draw_loaded_gun && contact);
    const int exposure = std::min(3, s.contacts) * 12 + (100 - s.hp) / 3 + (s.recent_damage ? 12 : 0);
    const int urgency = (s.committed ? 18 : 0) + (s.carrying ? 12 : 0) + (s.time_left < 75 ? 40 : 0);
    const int ammunition = s.ammo * 100 / std::max(1, s.magazine);
    const int sustain = std::min(25, s.ammo * 5);
    Options options{
        {{Choice::assignment, 48 + urgency + s.discipline / 10, exposure, !contact && s.interaction_left < 0},
         {Choice::engage, 60 + sustain + s.aggression / 5 + (s.entry ? 8 : 0),
          exposure * (150 - s.risk) / 150 + (weapon_busy ? 35 : 0), contact},
         {Choice::cover, 16 + exposure + s.reading / 8 + s.familiarity / 12 + (weapon_busy ? 30 : 0),
          s.aggression / 6 + urgency / 3, contact && s.interaction_left < 0},
         {Choice::watch, 22 + s.confidence / 3 + s.role_experience / 9 + (s.support ? 6 : 0),
          urgency + (s.entry ? 8 : 0), !contact && s.remembered && s.interaction_left < 0},
         {Choice::reload, 100 - ammunition + s.discipline / 12,
          s.confidence / 2 + urgency + s.reload_exposure + (s.recent_damage ? 30 : 0),
          !contact && !s.reload_ticks && s.reserve > 0 && ammunition < 55 && s.interaction_left < 0},
         {Choice::objective, 120 - std::min(55, std::max(0, s.interaction_left)), contact ? exposure / 2 : 0,
          s.interaction_left >= 0},
         {Choice::escape, 160, exposure / 3, s.can_escape && s.interaction_left < 0}}};
    if (execution)
        assess_execution(options, s, *execution);
    // The enum order resolves equal scores deterministically. Comparing
    // candidates neither consumes RNG nor executes moves.
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
