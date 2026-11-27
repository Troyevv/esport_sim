#pragma once
#include "collision.hpp"
#include "routes.hpp"

#include <mutex>

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
    std::optional<EscapePath> escape(AreaId area, const Point &start, const Point &bomb, double radius) const;

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
    mutable std::map<std::pair<EdgeId, Point>, std::optional<WalkPath>> gates_;

    Point world(const Point &p) const;
    Point sim(const Point &p) const;
    bool passage(Point p, Point q, bool climb) const;
    std::optional<WalkPath> inside(AreaId area, const Point &start, const Point &end,
                                   bool climb = false) const;
    std::optional<WalkPath> gate(EdgeId edge, const Point &start) const;
    std::optional<EscapePath> search(const State &start, std::optional<AreaId> zone, const Point &goal,
                                     const std::set<AreaId> &avoided, double radius) const;
};
} // namespace esport
