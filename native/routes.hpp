#pragma once

#include "navigation.hpp"

#include <memory>
#include <set>
#include <tuple>
#include <unordered_map>

namespace esport {
using AreaId = std::int64_t;
using EdgeId = std::size_t;
using Portal = std::tuple<AreaId, AreaId, double>;
using PortalPath = std::vector<EdgeId>;
using StagePath = std::pair<PortalPath, std::vector<AreaId>>;

class PortalGraph;

class StageRoutes {
public:
    std::map<AreaId, double> costs() const;
    std::optional<double> cost(AreaId start) const;
    std::optional<StagePath> route(AreaId start) const;

private:
    friend class PortalGraph;
    StageRoutes() = default;
    std::shared_ptr<const PortalGraph> graph_;
    std::vector<double> costs_;
    std::vector<std::vector<EdgeId>> stages_;
};

// Indices in a PortalPath refer to edges in original input order. Two parallel
// edges may connect the same areas but have different portal geometry.
class PortalGraph : public std::enable_shared_from_this<PortalGraph> {
public:
    static std::shared_ptr<PortalGraph> create(const std::map<AreaId, Point>& centers,
                                               const std::vector<Portal>& portals);
    std::optional<PortalPath> route(AreaId start, AreaId goal, const std::set<AreaId>& avoided,
                                    const std::set<std::pair<AreaId, AreaId>>& excluded) const;
    StageRoutes routes_through(const std::vector<std::vector<AreaId>>& choices) const;

private:
    friend class StageRoutes;
    friend class PhysicalNavigation;
    PortalGraph(const std::map<AreaId, Point>& centers, const std::vector<Portal>& portals);
    struct Node {
        AreaId id;
        Point center;
        std::vector<EdgeId> outgoing, incoming;
    };
    struct Edge {
        std::size_t from, to;
        double cost;
    };
    // Nodes are stored by increasing area ID, preserving Python heap tie order.
    std::vector<Node> nodes_;
    std::unordered_map<AreaId, std::size_t> index_;
    std::vector<Edge> edges_;
};
}
