#pragma once
#include "grid.hpp"
#include "perception.hpp"

namespace esport {
inline bool spatial_grenades(const Json &world) {
    return world.value("agentPolicy", 0) >= 6;
}
inline bool coordinated_utility(const Json &world) {
    return world.value("agentPolicy", 0) >= 7;
}
void receive_flash_warning(Json &actor, const Json &warning, const Json &sender, bool coordinated);
double flash_exposure(const Point &eye, double heading, const Point &burst, double radius);
void expose_player(Json &world, Json &actor, const Json &effect, double peak);
void recover_vision(Json &world);
void impaired(Json &actor, Tick now);
bool assisted_by_flash(const Json &actor, Tick now);
bool recognizes(const Json &actor, const Point &point, Tick now);
void count_utility(Json &world, const Json &owner, const std::string &metric, int amount = 1);

void spread_volume(Json &effect, const PhysicalNavigation *map, const GridMap *grid);
void update_volumes(Json &world, const PhysicalNavigation *map, const GridMap *grid);
void disturb_smoke(Json &world, const Point &from, const Point &to, bool blast, const Json &owner);
void append_volume(const Json &effect, std::vector<Hazard> &out);
bool crosses_volume(const Json &effect, const Point &from, const Point &to);
} // namespace esport
