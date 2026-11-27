#pragma once
#include "physical_navigation.hpp"

namespace esport {
std::array<int, 2> sound_direction(const Point &pos, const Point &source);
bool near_segment(const Point &a, const Point &b, const Point &p, double radius);
struct Observer {
    Point position;
    double heading;
    bool attack, blind;
};
struct Listener {
    Point position;
    double reading;
    bool eligible;
};
struct Heard {
    std::size_t listener;
    Point estimate;
    double confidence;
};
// Projection of physical stimuli. Indices refer to the supplied living players.
class MapSensors {
  public:
    MapSensors(std::shared_ptr<const PhysicalNavigation> map, std::vector<std::string> materials);
    std::vector<std::vector<std::size_t>> observe(const std::vector<Observer> &players,
                                                  const std::vector<Hazard> &smoke) const;
    std::vector<Heard> hear(const Point &source, double radius, const std::vector<Listener> &guards) const;
    double shot_transmission(const Point &start, const Point &end, double power) const;

  private:
    std::shared_ptr<const PhysicalNavigation> map_;
    std::vector<std::string> materials_;
};
} // namespace esport
