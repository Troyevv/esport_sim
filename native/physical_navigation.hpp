#pragma once
#include "collision.hpp"
#include "routes.hpp"

#include <list>
#include <mutex>
#include <unordered_map>

namespace esport {
using Lane = std::pair<Point, Point>;
struct Crossing {
    AreaId from, to;
    bool ladder;
    std::vector<Lane> lanes; // Ordered as exported, including the preferred lane.
};
using Waypoint = std::tuple<double, double, double, AreaId>;
using WalkPath = std::vector<Waypoint>;
using EscapePath = std::pair<double, WalkPath>;

using Destination = std::tuple<AreaId, Point, std::set<AreaId>>;
using Hazard = std::pair<Point, double>;
struct MotionState {
    Point position;
    AreaId area;
    double heading;
    int blocked_ticks;
    WalkPath path;
    std::optional<Destination> destination;
};
struct MoveResult {
    bool moved{}, waiting{}, replanned{};
    std::size_t consumed{};
};

class PhysicalNavigation {
  public:
    PhysicalNavigation(std::shared_ptr<const CollisionWorld> world, std::shared_ptr<const PortalGraph> graph,
                       std::shared_ptr<const NavSurfaces> surfaces, Point overview, double unit,
                       std::map<AreaId, Point> centers, std::vector<Area> areas, std::set<Point> mounts,
                       std::vector<Crossing> crossings);

    std::optional<WalkPath> path(AreaId area, const Point &start, AreaId zone, const Point &goal,
                                 const std::set<AreaId> &avoided) const;
    std::shared_ptr<const StageRoutes> safe_routes(const Point &bomb, double radius) const;
    std::optional<EscapePath> escape(AreaId area, const Point &start, const Point &bomb, double radius) const;

    std::optional<Impact> hit(const Point &start, const Point &end, unsigned mask, double up,
                              double target_up, bool canonical = false) const;
    const PortalGraph &graph() const { return *graph_; }
    const std::map<AreaId, Point> &centers() const { return centers_; }
    const Point &center(AreaId id) const { return centers_.at(id); }
    double unit() const { return unit_; }
    std::optional<AreaId> locate(const Point &p) const { return surfaces_->locate(world(p), 96); }
    Point world(const Point &p) const;
    std::optional<Point> use_position(AreaId start, const Point &origin, const Point &goal,
                                      double radius) const;
    std::optional<Point> nav_center(const Point &pos) const;
    MoveResult walk(MotionState &actor, const Point &goal, double pace,
                    const std::vector<Hazard> &fire) const;
    std::vector<Point> grenade(const Point &origin, const Point &target, int flight) const;

  private:
    using State = std::pair<AreaId, Point>;
    std::shared_ptr<const CollisionWorld> collision_;
    std::shared_ptr<const PortalGraph> graph_;
    std::shared_ptr<const NavSurfaces> surfaces_;
    Point overview_;
    double unit_;
    std::map<AreaId, Point> centers_;
    std::map<AreaId, std::vector<Point>> candidates_;
    std::set<Point> mounts_;
    std::vector<Crossing> crossings_;
    std::map<AreaId, std::vector<EdgeId>> outgoing_;
    mutable std::mutex mutex_;
    using SafeZones = std::pair<std::pair<Point, double>, std::shared_ptr<const StageRoutes>>;
    mutable std::list<SafeZones> safe_zones_;
    struct PositionedKeyHash {
        template <class Id> std::size_t operator()(const std::pair<Id, Point> &key) const noexcept {
            std::size_t seed = std::hash<Id>{}(key.first);
            for (double coordinate : key.second)
                seed ^= std::hash<double>{}(coordinate) + 0x9e3779b9u + (seed << 6) + (seed >> 2);
            return seed;
        }
    };
    mutable std::unordered_map<std::pair<EdgeId, Point>, std::optional<WalkPath>, PositionedKeyHash> gates_;
    using PathKey = std::tuple<AreaId, Point, AreaId, Point, std::set<AreaId>>;
    mutable std::map<PathKey, std::optional<WalkPath>> paths_;
    mutable std::map<std::tuple<AreaId, Point, Point, double>, std::optional<EscapePath>> escapes_;
    std::optional<WalkPath> find_path(AreaId area, const Point &start, AreaId zone, const Point &goal,
                                      const std::set<AreaId> &avoided) const;

    Point sim(const Point &p) const;
    bool passage(Point p, Point q, bool climb) const;
    std::optional<WalkPath> inside(AreaId area, const Point &start, const Point &end,
                                   bool climb = false) const;
    const std::optional<WalkPath> &gate(EdgeId edge, const Point &start) const;
    std::optional<EscapePath> search(const State &start, std::optional<AreaId> zone, const Point &goal,
                                     const std::set<AreaId> &avoided, double radius) const;
};
} // namespace esport
