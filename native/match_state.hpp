#pragma once

#include "physical_navigation.hpp"
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace esport {
class PhysicalNavigation;
class Objectives;
// Owns a single detailed match. External snapshots are copied only at an explicit
// boundary. No Python objects or callbacks are retained by the owner.
class MatchState {
  public:
    MatchState(const std::string &checkpoint, std::string current_rules, std::set<std::string> old_rules,
               std::set<std::string> calls, int freeze_ticks, int map_build, const std::string &rulebook);
    ~MatchState();
    std::string snapshot() const;
    std::string board_step(const std::string &id, const std::string &device, const std::vector<Hazard> &fire);
    void assign_board(const std::string &board);
    std::string buy_decision(const std::string &side, const std::string &options) const;
    void buy_equipment(const std::string &side, const std::string &strategy, const std::string &board);
    void command(const std::string &kind, const std::string &value);
    int advance_intermission(int ticks);
    void deliver_radio();
    void attach_spawns(const std::string &map, const std::string &spawns);
    void attach_physics(const std::string &map, std::shared_ptr<const PhysicalNavigation> planner,
                        std::vector<std::string> materials);
    void apply_effects();
    void observe();
    void attach_objectives(const std::string &map, std::shared_ptr<const Objectives> sites);
    void resolve_intents(const std::string &intents);
    void resolve_actions(const std::string &intents);
    void finish_round(const std::string &side, const std::string &reason);

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace esport
