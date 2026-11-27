#pragma once
#include "combat.hpp"

namespace esport {
using Triangle = std::array<Point, 3>;
using Ingress = std::map<std::string, std::array<std::vector<Point>, 2>>;
struct SiteData {
    std::map<std::string, std::vector<std::vector<Triangle>>> solids;
    std::map<std::string, std::map<AreaId, double>> costs;
    std::map<std::string, std::vector<Point>> samples;
    Ingress ingress;
};
class Objectives {
  public:
    explicit Objectives(std::shared_ptr<const GridMap> grid) : grid_(std::move(grid)) {}
    Objectives(std::shared_ptr<const PhysicalNavigation> map, SiteData sites);
    std::optional<std::string> site_at(const Point &position) const;
    std::optional<std::string> reported_site(const Point &p) const;
    const std::vector<Point> &samples(const std::string &site) const { return samples_.at(site); }
    double site_cost(const std::string &site, AreaId area, double fallback) const {
        const auto &costs = costs_.at(site);
        auto found = costs.find(area);
        return found == costs.end() ? fallback : found->second;
    }
    const Ingress &ingress() const { return ingress_; }
    const GridMap *grid() const { return grid_.get(); }
    const PhysicalNavigation &map() const {
        if (!map_)
            throw std::invalid_argument("Требуется физическая карта");
        return *map_;
    }
    void resolve(Json &w, const Json &cfg, const Json &ordered) const;

  private:
    struct Solid {
        Point low, high;
        std::vector<Triangle> triangles;
    };
    std::shared_ptr<const PhysicalNavigation> map_;
    std::shared_ptr<const GridMap> grid_;
    std::map<std::string, std::vector<Solid>> volumes_;
    std::map<std::string, std::map<AreaId, double>> costs_;
    std::map<std::string, std::vector<Point>> samples_;
    Ingress ingress_;
    void hear_plant(Json &w, const Point &p) const;
    void interact(Json &w, const Json &cfg, Json &actor, const std::string &kind, Json site = nullptr) const;
};
} // namespace esport
