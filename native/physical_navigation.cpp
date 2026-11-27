#include "physical_navigation.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>

namespace esport {
namespace {
template <class T> using Queue = std::priority_queue<T, std::vector<T>, std::greater<T>>;
void check_point(const Point &p) {
    if (!std::ranges::all_of(p, [](double x) { return std::isfinite(x); }))
        throw std::invalid_argument("Non-finite navigation point");
}
Point lerp(const Point &a, const Point &b, double t) {
    return {a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t};
}
// Compensate the rounding of each square and addition before rounding the
// root. Path costs must preserve math.dist tie ordering, including on MSVC.
double distance(const Point &a, const Point &b) {
    double sum = 0, error = 0;
    for (int j = 0; j < 3; ++j) {
        const double d = a[j] - b[j], square = d * d, next = sum + square;
        error += std::fma(d, d, -square);
        error += sum >= square ? (sum - next) + square : (square - next) + sum;
        sum = next;
    }
    if (sum == 0)
        return 0;
    const double root = std::sqrt(sum);
    return root + (std::fma(-root, root, sum) + error) / (2 * root);
}
Waypoint waypoint(const Point &p, AreaId area) { return {p[0], p[1], p[2], area}; }
Point point(const Waypoint &p) { return {std::get<0>(p), std::get<1>(p), std::get<2>(p)}; }
template <class Key> bool improves(const std::map<Key, double> &costs, const Key &key, double value) {
    const auto it = costs.find(key);
    return it == costs.end() || value < it->second;
}
} // namespace

PhysicalNavigation::PhysicalNavigation(std::shared_ptr<const CollisionWorld> collision,
                                       std::shared_ptr<const PortalGraph> graph,
                                       std::shared_ptr<const NavSurfaces> surfaces, Point overview,
                                       double unit, std::map<AreaId, Point> centers, std::vector<Area> areas,
                                       std::set<Point> mounts, std::vector<Crossing> crossings)
    : collision_(std::move(collision)), graph_(std::move(graph)), surfaces_(std::move(surfaces)),
      overview_(overview), unit_(unit), centers_(std::move(centers)), mounts_(std::move(mounts)),
      crossings_(std::move(crossings)) {
    if (!collision_ || !graph_ || !surfaces_ || !(unit_ > 0 && std::isfinite(unit_)))
        throw std::invalid_argument("Invalid physical world");
    check_point(overview_);
    for (const auto &[id, center] : centers_)
        check_point(center);
    for (const auto &mount : mounts_)
        check_point(mount);
    if (graph_->edges_.size() != crossings_.size())
        throw std::invalid_argument("Physical portal count differs");
    for (const auto &[area, corners] : areas) {
        for (const auto &corner : corners)
            check_point(corner);
        if (corners.size() < 3 || candidates_.contains(area))
            throw std::invalid_argument("Invalid physical surface");
        const auto &center = centers_.at(area);
        auto &candidates = candidates_[area];
        candidates.push_back(center);
        for (std::size_t i = 0; i < corners.size(); ++i)
            for (double t : {0., 0.5}) {
                const auto edge = sim(lerp(corners[i], corners[(i + 1) % corners.size()], t));
                for (double fraction : {0.45, 0.9}) {
                    auto p = lerp(center, edge, fraction);
                    const auto w = world(p);
                    if (auto z = surface_height(corners, w[0], w[1])) {
                        p[2] = *z / unit_;
                        if (std::find(candidates.begin(), candidates.end(), p) == candidates.end())
                            candidates.push_back(p);
                    }
                }
            }
    }
    for (EdgeId i = 0; i < crossings_.size(); ++i) {
        const auto &edge = crossings_[i];
        if (!candidates_.contains(edge.from) || !candidates_.contains(edge.to) || edge.lanes.empty())
            throw std::invalid_argument("Invalid physical portal");
        const auto &graph_edge = graph_->edges_[i];
        if (graph_->nodes_[graph_edge.from].id != edge.from || graph_->nodes_[graph_edge.to].id != edge.to)
            throw std::invalid_argument("Physical portal order differs");
        for (const auto &[a, b] : edge.lanes) {
            check_point(a);
            check_point(b);
        }
        outgoing_[edge.from].push_back(i);
    }
}

Point PhysicalNavigation::world(const Point &p) const {
    return {overview_[0] + p[0] * unit_, overview_[1] - p[1] * unit_, p[2] * unit_};
}
Point PhysicalNavigation::sim(const Point &p) const {
    return {(p[0] - overview_[0]) / unit_, (overview_[1] - p[1]) / unit_, p[2] / unit_};
}
bool PhysicalNavigation::passage(Point p, Point q, bool climb) const {
    if (p == q)
        return true;
    p = world(p);
    q = world(q);
    p[2] += 34;
    q[2] += 34;
    return !collision_->trace(p, q, climb ? 16 : 2);
}

std::optional<WalkPath> PhysicalNavigation::inside(AreaId area, const Point &start, const Point &end,
                                                   bool climb) const {
    climb = climb || mounts_.contains(start);
    if (passage(start, end, climb))
        return WalkPath{waypoint(end, area)};
    const auto &candidates = candidates_.at(area);
    Queue<std::tuple<double, double, Point>> queue;
    std::map<Point, double> costs{{start, 0}};
    std::map<Point, Point> parents;
    queue.emplace(distance(start, end), 0, start);
    while (!queue.empty()) {
        const auto [rank, length, pos] = queue.top();
        queue.pop();
        if (length != costs.at(pos))
            continue;
        if (pos == end) {
            WalkPath result;
            for (Point q = end; q != start; q = parents.at(q))
                result.push_back(waypoint(q, area));
            std::reverse(result.begin(), result.end());
            return result;
        }
        auto visit = [&](const Point &next) {
            const double n = length + distance(pos, next);
            if (!improves(costs, next, n) || !passage(pos, next, climb))
                return;
            costs[next] = n;
            parents[next] = pos;
            queue.emplace(n + distance(next, end), n, next);
        };
        for (const auto &next : candidates)
            visit(next);
        visit(end);
    }
    return std::nullopt;
}
std::optional<WalkPath> PhysicalNavigation::gate(EdgeId id, const Point &start) const {
    const auto key = std::pair{id, start};
    if (const auto it = gates_.find(key); it != gates_.end())
        return it->second;
    const auto &edge = crossings_.at(id);
    std::optional<WalkPath> best;
    for (const auto &[a, b] : edge.lanes) {
        const auto leave = sim(a), enter = sim(b);
        auto leg = inside(edge.from, start, leave, edge.ladder);
        if (!leg)
            continue;
        if (!passage(leave, enter, edge.ladder)) {
            const auto dz = std::abs(a[2] - b[2]);
            if (edge.ladder || dz <= 1 || dz > 64)
                continue;
            Point corner = leave[2] < enter[2] ? leave : enter;
            corner[2] = std::max(leave[2], enter[2]) + 0.1;
            if (!passage(leave, corner, false) || !passage(corner, enter, false))
                continue;
            leg->push_back(waypoint(corner, edge.from));
        }
        leg->push_back(waypoint(enter, edge.to));
        best = std::move(leg);
        break;
    }
    if (gates_.size() >= 32768)
        gates_.clear();
    gates_.emplace(key, best);
    return best;
}

std::optional<WalkPath> PhysicalNavigation::path(AreaId area, const Point &start, AreaId zone,
                                                 const Point &goal, const std::set<AreaId> &avoided) const {
    check_point(start);
    check_point(goal);
    std::scoped_lock lock(mutex_);
    auto route = graph_->route(area, zone, avoided, {});
    if (!route)
        return std::nullopt;
    WalkPath path;
    Point pos = start;
    bool complete = true;
    for (const auto edge : *route) {
        auto leg = gate(edge, pos);
        if (!leg) {
            complete = false;
            break;
        }
        path.insert(path.end(), leg->begin(), leg->end());
        pos = point(path.back());
    }
    if (complete) {
        if (auto end = inside(zone, pos, goal)) {
            path.insert(path.end(), end->begin(), end->end());
            return path;
        }
    }
    if (auto result = search({area, start}, zone, goal, avoided, 0))
        return std::move(result->second);
    return std::nullopt;
}

std::optional<EscapePath> PhysicalNavigation::escape(AreaId area, const Point &start, const Point &bomb,
                                                     double radius) const {
    check_point(start);
    check_point(bomb);
    if (!(std::isfinite(radius) && radius >= 0))
        throw std::invalid_argument("Invalid safe radius");
    if (!centers_.contains(area))
        return std::nullopt;
    std::scoped_lock lock(mutex_);
    return search({area, start}, std::nullopt, bomb, {}, radius);
}
std::optional<EscapePath> PhysicalNavigation::search(const State &start, std::optional<AreaId> zone,
                                                     const Point &goal, const std::set<AreaId> &avoided,
                                                     double radius) const {
    auto estimate = [&](const Point &pos) {
        double d = distance(pos, goal);
        return zone ? d : std::max(0., radius - d);
    };
    std::map<State, double> costs{{start, 0}};
    std::map<State, std::pair<State, WalkPath>> parents;
    Queue<std::tuple<double, double, State>> queue;
    queue.emplace(estimate(start.second), 0, start);
    while (!queue.empty()) {
        const auto [rank, length, state] = queue.top();
        queue.pop();
        if (length != costs.at(state))
            continue;
        const auto &[here, pos] = state;
        std::optional<WalkPath> end;
        if (zone == here)
            end = inside(here, pos, goal);
        if (!zone && estimate(pos) == 0 && surfaces_->locate(world(pos), 96))
            end.emplace();
        if (end) {
            WalkPath result;
            for (auto step = state; step != start;) {
                const auto &[prev, leg] = parents.at(step);
                result.insert(result.end(), leg.rbegin(), leg.rend());
                step = prev;
            }
            std::reverse(result.begin(), result.end());
            result.insert(result.end(), end->begin(), end->end());
            return EscapePath{length, std::move(result)};
        }
        auto visit = [&](const WalkPath &leg) {
            const State target{std::get<3>(leg.back()), point(leg.back())};
            if (avoided.contains(target.first))
                return;
            auto prev = pos;
            double traveled = length;
            for (const auto &node : leg) {
                const auto q = point(node);
                traveled += distance(prev, q);
                prev = q;
            }
            if (!improves(costs, target, traveled))
                return;
            costs[target] = traveled;
            parents[target] = {state, leg};
            queue.emplace(traveled + estimate(target.second), traveled, target);
        };
        if (auto it = outgoing_.find(here); it != outgoing_.end())
            for (auto id : it->second)
                if (auto leg = gate(id, pos))
                    visit(*leg);
        if (!zone) {
            const auto &center = centers_.at(here);
            if (pos != center && estimate(center) == 0)
                if (auto leg = inside(here, pos, center))
                    visit(*leg);
        }
    }
    return std::nullopt;
}
} // namespace esport
