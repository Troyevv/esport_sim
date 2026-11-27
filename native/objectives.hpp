#pragma once
#include "combat.hpp"

namespace esport {
using Triangle = std::array<Point, 3>;
struct SiteData {
    std::map<std::string, std::vector<std::vector<Triangle>>> solids;
    std::map<std::string, std::map<AreaId, double>> costs;
    std::map<std::string, std::vector<Point>> samples;
};
class Objectives {
  public:
    Objectives(std::shared_ptr<const PhysicalNavigation> map, SiteData sites);
    std::optional<std::string> site_at(const Point &position) const;
    void resolve(Json &w, const Json &cfg, const Json &ordered) const;

  private:
    struct Solid {
        Point low, high;
        std::vector<Triangle> triangles;
    };
    std::shared_ptr<const PhysicalNavigation> map_;
    std::map<std::string, std::vector<Solid>> volumes_;
    std::map<std::string, std::map<AreaId, double>> costs_;
    std::map<std::string, std::vector<Point>> samples_;
    void hear_plant(Json &w, const Point &p) const;
    void interact(Json &w, const Json &cfg, Json &actor, const std::string &kind) const;
};
} // namespace esport
