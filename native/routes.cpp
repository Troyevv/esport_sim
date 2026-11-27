#include "routes.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <queue>
#include <stdexcept>

namespace esport {
namespace {
constexpr double inf = std::numeric_limits<double>::infinity();
constexpr EdgeId no_edge = std::numeric_limits<EdgeId>::max();
template <typename T>
using MinHeap = std::priority_queue<T, std::vector<T>, std::greater<T>>;
}

std::shared_ptr<PortalGraph> PortalGraph::create(const std::map<AreaId, Point>& centers,
                                                  const std::vector<Portal>& portals) {
    return std::shared_ptr<PortalGraph>(new PortalGraph(centers, portals));
}

PortalGraph::PortalGraph(const std::map<AreaId, Point>& centers, const std::vector<Portal>& portals) {
    for (const auto& [id, center] : centers) {
        if (!std::all_of(center.begin(), center.end(), [](double x) { return std::isfinite(x); }))
            throw std::invalid_argument("Non-finite area center");
        index_.emplace(id, nodes_.size());
        nodes_.push_back({id, center, {}, {}});
    }
    for (const auto& [from, to, cost] : portals) {
        if (!index_.contains(from) || !index_.contains(to) || !std::isfinite(cost) || cost < 0)
            throw std::invalid_argument("Invalid directed portal");
        auto source = index_.at(from), target = index_.at(to);
        nodes_[source].outgoing.push_back(edges_.size());
        nodes_[target].incoming.push_back(edges_.size());
        edges_.push_back({source, target, cost});
    }
}

std::optional<PortalPath> PortalGraph::route(AreaId start, AreaId goal, const std::set<AreaId>& avoided,
                                             const std::set<std::pair<AreaId, AreaId>>& excluded) const {
    if (!index_.contains(start) || !index_.contains(goal) || avoided.contains(goal)) return std::nullopt;
    auto first = index_.at(start), last = index_.at(goal);
    const auto& dest = nodes_[last].center;
    auto estimate = [&](std::size_t i) {
        const auto& p = nodes_[i].center;
        return std::hypot(p[0] - dest[0], p[1] - dest[1], p[2] - dest[2]);
    };
    MinHeap<std::tuple<double, double, std::size_t>> queue;
    std::vector<double> costs(nodes_.size(), inf);
    std::vector<EdgeId> parent(nodes_.size(), no_edge);
    costs[first] = 0;
    queue.emplace(estimate(first), 0, first);
    while (!queue.empty()) {
        const auto [rank, cost, here] = queue.top();
        queue.pop();
        if (cost != costs[here]) continue;
        if (here == last) {
            PortalPath path;
            for (auto pos = last; pos != first; pos = edges_[parent[pos]].from)
                path.push_back(parent[pos]);
            std::reverse(path.begin(), path.end());
            return path;
        }
        for (auto id : nodes_[here].outgoing) {
            const auto& edge = edges_[id];
            AreaId other = nodes_[edge.to].id;
            if (avoided.contains(other) || excluded.contains({nodes_[here].id, other})) continue;
            double length = cost + edge.cost;
            if (length >= costs[edge.to]) continue;
            parent[edge.to] = id;
            costs[edge.to] = length;
            queue.emplace(length + estimate(edge.to), length, edge.to);
        }
    }
    return std::nullopt;
}

StageRoutes PortalGraph::routes_through(const std::vector<std::vector<AreaId>>& choices) const {
    StageRoutes plan;
    plan.graph_ = shared_from_this();
    plan.costs_.resize(nodes_.size(), 0);
    for (auto stage = choices.rbegin(); stage != choices.rend(); ++stage) {
        MinHeap<std::pair<double, std::size_t>> queue;
        std::vector<double> costs(nodes_.size(), inf);
        std::vector<EdgeId> onward(nodes_.size(), no_edge);
        for (auto area : *stage) {
            auto node = index_.find(area);
            if (node == index_.end()) continue;
            auto i = node->second;
            if (plan.costs_[i] < costs[i]) {
                costs[i] = plan.costs_[i];
                queue.emplace(costs[i], i);
            }
        }
        while (!queue.empty()) {
            const auto [remaining, area] = queue.top();
            queue.pop();
            if (remaining != costs[area]) continue;
            for (auto id : nodes_[area].incoming) {
                const auto& edge = edges_[id];
                double candidate = remaining + edge.cost;
                if (candidate < costs[edge.from]) {
                    costs[edge.from] = candidate;
                    onward[edge.from] = id;
                    queue.emplace(candidate, edge.from);
                }
            }
        }
        plan.stages_.push_back(std::move(onward));
        plan.costs_ = std::move(costs);
    }
    std::reverse(plan.stages_.begin(), plan.stages_.end());
    return plan;
}

std::map<AreaId, double> StageRoutes::costs() const {
    std::map<AreaId, double> result;
    for (std::size_t i = 0; i < costs_.size(); ++i) {
        if (std::isfinite(costs_[i])) result.emplace(graph_->nodes_[i].id, costs_[i]);
    }
    return result;
}

std::optional<StagePath> StageRoutes::route(AreaId start) const {
    auto entry = graph_->index_.find(start);
    if (entry == graph_->index_.end() || !std::isfinite(costs_[entry->second])) return std::nullopt;
    auto here = entry->second;
    StagePath result;
    for (const auto& stage : stages_) {
        while (stage[here] != no_edge) {
            auto id = stage[here];
            result.first.push_back(id);
            here = graph_->edges_[id].to;
        }
        result.second.push_back(graph_->nodes_[here].id);
    }
    return result;
}
}
