#pragma once
#include "objectives.hpp"

namespace esport {
inline bool collective_attack(const Json &world) { return world.value("agentPolicy", 0) >= 8; }
using Contest = std::pair<std::map<AreaId, double>, double>;
using ContestTable = std::map<std::string, std::array<Contest, 2>>;
using Stations = std::map<std::string, std::vector<Point>>;
struct OrderData {
    std::map<std::string, std::vector<AreaId>> places, plants;
    std::map<std::string, std::vector<std::pair<AreaId, Point>>> holds;
    std::map<AreaId, std::vector<AreaId>> nearby;
    std::vector<std::string> roles;
    std::vector<Point> cover;
    std::vector<AreaId> attack_spawns;
    std::map<AreaId,std::vector<Point>> plant_corners;
};
class OpeningMap {
  public:
    explicit OpeningMap(std::shared_ptr<const Objectives> obj) : objectives_(std::move(obj)) {}
    OpeningMap(std::shared_ptr<const Objectives> objectives, const std::string &profile,
               const std::string &defense, ContestTable contest, Stations stations,
               std::map<std::string, Point> sites, OrderData orders);
    Json call(Json &w, Json &captain, const Json &buy, std::string site, std::string style,
              const Json &coach) const;
    Json select_defense(const Json &w, Json &captain, const Json &plan, const Json &predicted,
                        const Json &explicit_site) const;
    std::string draft(const Json &w, Json &captain, Json &plan, const Json &predicted,
                      const Json &explicit_site) const;
    void equip_defense(const Json &w, Json &plan, const Json &cfg) const;
    Json positions(const std::string &zone, const Point &origin, bool cautious) const;
    Json lineup(const Point &origin, const Point &gate, const Point &peek, const Point &watch,
                const std::string &item, double radius) const;
    const Objectives &objectives() const { return *objectives_; }
    const Json &profile() const { return profile_; }
    const Contest& contest(const std::string& site,int lane) const {return contest_.at(site).at(lane);}
    const OrderData &layout() const { return orders_; }
    const Point &site_point(const std::string &site) const { return sites_.at(site); }
    void begin_live(Json &w, const Json &cfg) const;
    Json defense_orders(const Json &w, const std::string &site, int lane) const;
    using Angles = std::vector<std::pair<Point, Point>>;
    Angles angles(const std::string &site, int lane, const Point &anchor, const std::string &duty) const;
    Angles crossfire(const std::string &site, int lane, const Point &wing, const Point &anchor,
                     const Point &watch) const;
    Json screen(const std::string &site, int lane, const Point &origin, const Point &hold, const Point &watch,
                const Point &anchor, const Point &partner_watch) const;
    Point watch(const std::string &site, int lane, const Point &from) const;
    Json attack_orders(const Json &w, const std::string &site, int lane, const std::string &style) const;
    Json default_probe(const Json &w, const Json &plan, const Json &cfg) const;

  private:
    std::shared_ptr<const Objectives> objectives_;
    Json profile_, defense_;
    ContestTable contest_;
    Stations stations_;
    OrderData orders_;
    std::map<std::pair<std::string, int>, StageRoutes> approaches_;
    std::map<std::string, Point> sites_;
};
Json defensive_read(const Json &w, const Json &captain);
} // namespace esport
