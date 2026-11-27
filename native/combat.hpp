#pragma once
#include "grid.hpp"
#include "perception.hpp"
#include "round_rules.hpp"

namespace esport {
int weapon_accuracy(const Json& w,const Json& cfg,const Json& a,const Json& spec,double gap,int burst);
class Combat {
  public:
    Combat(std::shared_ptr<const PhysicalNavigation> planner, std::vector<std::string> materials);
    explicit Combat(std::shared_ptr<const GridMap> grid) : grid_(std::move(grid)) {}
    const MapSensors &sensors() const { return sensors_.value(); }
    void hear(Json &w, const Json &source, const std::string &kind, double radius) const;
    void effects(Json &state, const Json &cfg) const;
    void execute(Json &w, const Json &cfg, const Json &intents) const;

  private:
    std::shared_ptr<const PhysicalNavigation> planner_;
    std::optional<MapSensors> sensors_;
    std::shared_ptr<const GridMap> grid_;
    void report_shot(Json &w, const Json &actor, const Json &target) const;
    Json sound_position(const Point &source) const;
    void shoot(Json &w, const Json &cfg, Json &agent, const Json &target, Json *victim) const;
    void throw_grenade(Json &w, const Json &cfg, Json &agent, const Json &target) const;
};
void apply_impact(Json &w, const Json &cfg, Json &shooter, Json &victim, double base,
                  const std::string &weapon, const std::string &group);
} // namespace esport
