#include "physical_navigation.hpp"
#include <numbers>

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
} // namespace

namespace {
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
    const PathKey key{area, start, zone, goal, avoided};
    if (auto found = paths_.find(key); found != paths_.end())
        return found->second;
    if (paths_.size() >= 4096)
        paths_.clear();
    return paths_.emplace(key, find_path(area, start, zone, goal, avoided)).first->second;
}
std::optional<WalkPath> PhysicalNavigation::find_path(AreaId area, const Point &start, AreaId zone,
                                                      const Point &goal,
                                                      const std::set<AreaId> &avoided) const {
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
    const auto key = std::tuple{area, start, bomb, radius};
    if (auto found = escapes_.find(key); found != escapes_.end())
        return found->second;
    if (escapes_.size() >= 1024)
        escapes_.clear();
    return escapes_.emplace(key, search({area, start}, std::nullopt, bomb, {}, radius)).first->second;
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

namespace esport {
namespace {
bool enters_fire(const Point &start, const Point &next, const Hazard &hazard) {
    const auto &[center, radius] = hazard;
    if (distance(start, center) < radius)
        return false;
    const double dx = next[0] - start[0], dy = next[1] - start[1], dz = next[2] - start[2];
    const double span = sum3(dx * dx, dy * dy, dz * dz);
    const double projection =
        sum3((center[0] - start[0]) * dx, (center[1] - start[1]) * dy, (center[2] - start[2]) * dz);
    const double t = span ? std::clamp(projection / span, 0., 1.) : 0;
    return distance(lerp(start, next, t), center) < radius;
}
} // namespace

MoveResult PhysicalNavigation::walk(MotionState &actor, const Point &goal, double pace,
                                    const std::vector<Hazard> &fire) const {
    check_point(actor.position);
    check_point(goal);
    if (!std::isfinite(pace))
        throw std::invalid_argument("Invalid walking pace");
    if (!std::isfinite(actor.heading) || actor.blocked_ticks < 0 ||
        actor.blocked_ticks == std::numeric_limits<int>::max())
        throw std::invalid_argument("Invalid movement state");
    for (const auto &step : actor.path)
        check_point(point(step));
    MoveResult result;
    if (distance(goal, actor.position) < 1e-6) {
        actor.blocked_ticks = 0;
        return result;
    }
    auto zone = surfaces_->locate(world(goal), 96);
    if (!zone) {
        ++actor.blocked_ticks;
        return result;
    }
    std::set<AreaId> avoided;
    for (const auto &[center, radius] : fire) {
        check_point(center);
        if (!std::isfinite(radius))
            throw std::invalid_argument("Invalid fire radius");
        for (const auto &[id, pos] : centers_)
            if (id != actor.area && id != *zone && distance(center, pos) < radius)
                avoided.insert(id);
    }
    Destination dest{*zone, goal, avoided};
    bool crossing = !actor.path.empty() && std::get<3>(actor.path.front()) != actor.area;
    if ((!crossing && dest != actor.destination) || actor.path.empty()) {
        auto route = path(actor.area, actor.position, *zone, goal, avoided);
        if (!route && !avoided.empty())
            route = path(actor.area, actor.position, *zone, goal, {});
        if (!route) {
            ++actor.blocked_ticks;
            return result;
        }
        actor.path = std::move(*route);
        actor.destination = std::move(dest);
        result.replanned = true;
    }
    actor.blocked_ticks = 0;
    for (const auto &node : actor.path) {
        if (pace <= 0)
            break;
        auto endpoint = point(node);
        auto length = distance(actor.position, endpoint);
        if (length > 0) {
            const double fraction = std::min(1., pace / length);
            auto next = fraction < 1 ? lerp(actor.position, endpoint, fraction) : endpoint;
            if (std::ranges::any_of(fire,
                                    [&](const Hazard &h) { return enters_fire(actor.position, next, h); })) {
                result.waiting = true;
                break;
            }
            const double dx = next[0] - actor.position[0], dy = next[1] - actor.position[1];
            if (std::hypot(dx, dy) > 1e-6)
                actor.heading = std::atan2(dy, dx);
            actor.position = next;
            result.moved = true;
        }
        pace -= length;
        if (pace >= 0) {
            actor.area = std::get<3>(node);
            ++result.consumed;
        }
    }
    actor.path.erase(actor.path.begin(), actor.path.begin() + result.consumed);
    return result;
}

std::vector<Point> PhysicalNavigation::grenade(const Point &origin, const Point &target, int flight) const {
    check_point(origin);
    check_point(target);
    if (flight <= 0)
        throw std::invalid_argument("Invalid grenade flight duration");
    Point pos = origin;
    pos[2] += 4;
    const double gravity = 8. * std::min(18, flight) / (double(flight) * flight);
    Point velocity;
    for (int i = 0; i < 3; ++i)
        velocity[i] = (target[i] - pos[i]) / flight;
    velocity[2] += gravity * (flight - 1) / 2;
    std::vector<Point> track{pos};
    for (int step = 0; step < flight; ++step) {
        double remaining = 1;
        for (int bounce = 0; bounce < 4; ++bounce) {
            Point end;
            for (int j = 0; j < 3; ++j)
                end[j] = pos[j] + velocity[j] * remaining;
            auto hit = collision_->trace(world(pos), world(end), 8, step == flight - 1);
            if (!hit) {
                pos = end;
                break;
            }
            const double t = std::get<0>(*hit);
            Point normal = std::get<2>(*hit).value();
            double incidence =
                sum3(velocity[0] * normal[0], velocity[1] * normal[1], velocity[2] * normal[2]);
            if (incidence > 0) {
                incidence = -incidence;
                for (auto &v : normal)
                    v = -v;
            }
            for (int j = 0; j < 3; ++j) {
                pos[j] = pos[j] + velocity[j] * remaining * t + normal[j] * 0.02;
                velocity[j] = 0.65 * (velocity[j] - 1.55 * incidence * normal[j]);
            }
            remaining *= 1 - t;
        }
        track.push_back(pos);
        velocity[2] -= gravity;
    }
    return track;
}
} // namespace esport

namespace esport {
std::optional<Impact> PhysicalNavigation::hit(const Point &start, const Point &end, unsigned mask, double up,
                                              double target_up, bool canonical) const {
    auto a = world(start), b = world(end);
    a[2] += up;
    b[2] += target_up;
    if (canonical && b < a)
        std::swap(a, b);
    return collision_->trace(a, b, mask);
}
} // namespace esport

namespace esport {
std::shared_ptr<const StageRoutes> PhysicalNavigation::safe_routes(const Point &bomb, double radius) const {
    const auto key = std::pair{bomb, radius};
    std::scoped_lock lock(mutex_);
    auto it = std::find_if(safe_zones_.begin(), safe_zones_.end(),
                           [&](const auto &item) { return item.first == key; });
    if (it == safe_zones_.end()) {
        std::vector<AreaId> safe;
        for (auto &[id, p] : centers_)
            if (distance(p, bomb) >= radius)
                safe.push_back(id);
        safe_zones_.emplace_front(key, std::make_shared<StageRoutes>(graph_->routes_through({safe})));
        if (safe_zones_.size() > 16)
            safe_zones_.pop_back();
    } else
        safe_zones_.splice(safe_zones_.begin(), safe_zones_, it);
    return safe_zones_.front().second;
}

std::optional<Point> PhysicalNavigation::use_position(AreaId start, const Point &origin, const Point &goal,
                                                      double radius) const {
    if (auto at = locate(goal); at && path(start, origin, *at, goal, {}) && !hit(goal, goal, 1, 64, 5))
        return goal;
    std::vector<Point> choices;
    for (double step : {radius * .85, radius * .4})
        for (int i = 0; i < 12; ++i) {
            auto angle = 2 * std::numbers::pi * i / 12;
            Point q{goal[0] + step * std::cos(angle), goal[1] + step * std::sin(angle), goal[2]};
            if (auto floor = surfaces_->locate_with_height(world(q), radius * unit_)) {
                q[2] = floor->second / unit_;
                if (distance(q, goal) <= radius && !hit(q, goal, 1, 64, 5))
                    choices.push_back(q);
            }
        }
    std::stable_sort(choices.begin(), choices.end(),
                     [&](const auto &a, const auto &b) { return distance(a, origin) < distance(b, origin); });
    for (auto &q : choices)
        if (auto at = locate(q); at && path(start, origin, *at, q, {}))
            return q;
    return {};
}
std::optional<Point> PhysicalNavigation::nav_center(const Point &pos) const {
    if (auto area = surfaces_->locate(world(pos), 96))
        return centers_.at(*area);
    return std::nullopt;
}
} // namespace esport
