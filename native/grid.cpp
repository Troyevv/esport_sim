#include "grid.hpp"
#include <algorithm>
#include <cmath>
#include <deque>
#include <numbers>
namespace esport {
XY xy(const Json &a) { return {a.at("x"), a.at("y")}; }
double gap2(XY a, XY b) { return std::hypot(a[0] - b[0], a[1] - b[1]); }
namespace {
std::array<Cell, 4> neighbors(Cell p) {
    auto [x, y] = p;
    return {{{x + 1, y}, {x, y + 1}, {x - 1, y}, {x, y - 1}}};
}
} // namespace
GridMap::GridMap(const Json &input)
    : data(input), unit(input.at("cell")), vision(input.at("vision")),
      ordered(input.at("floor").get<std::vector<Cell>>()) {
    floor.insert(ordered.begin(), ordered.end());
    if (unit <= 0 || floor.empty())
        throw std::invalid_argument("Некорректная геометрия Депо");
}
Cell GridMap::cell(XY p) const { return {int(std::floor(p[0] / unit)), int(std::floor(p[1] / unit))}; }
XY GridMap::center(Cell p) const { return {p.first * unit + int(unit) / 2, p.second * unit + int(unit) / 2}; }
Json GridMap::point(Cell p) const {
    auto q = center(p);
    return Json::array({int(q[0]), int(q[1])});
}
bool GridMap::clear(XY a, XY b) const {
    auto [x, y] = cell(a);
    auto end = cell(b);
    auto dx = b[0] - a[0], dy = b[1] - a[1];
    int sx = dx > 0 ? 1 : -1, sy = dy > 0 ? 1 : -1;
    double nx = dx > 0 ? (x + 1) * unit - a[0] : a[0] - x * unit,
           ny = dy > 0 ? (y + 1) * unit - a[1] : a[1] - y * unit;
    while (floor.contains({x, y})) {
        if (Cell{x, y} == end)
            return true;
        auto cx = nx * std::abs(dy), cy = ny * std::abs(dx);
        if (dx && (!dy || cx < cy)) {
            x += sx;
            nx += unit;
        } else if (dy && (!dx || cy < cx)) {
            y += sy;
            ny += unit;
        } else {
            if (!floor.contains({x + sx, y}) || !floor.contains({x, y + sy}))
                return false;
            x += sx;
            y += sy;
            nx += unit;
            ny += unit;
        }
    }
    return false;
}
bool GridMap::sees(const Json &a, const Json &b) const {
    auto start = xy(a), end = xy(b);
    auto dx = end[0] - start[0], dy = end[1] - start[1], d = dx * dx + dy * dy,
         h = a.at("heading").get<double>(), dot = dx * std::cos(h) + dy * std::sin(h);
    return d <= vision * vision && dot >= 0 && 4 * dot * dot >= d && clear(start, end);
}
Json GridMap::sound(XY p) const {
    auto x = 3 * std::floor(p[0] / 30) + 1, y = 3 * std::floor(p[1] / 30) + 1;
    auto key = [&](Cell c) {
        auto dx = c.first - x, dy = c.second - y;
        return dx * dx + dy * dy;
    };
    auto result = point(
        *std::min_element(ordered.begin(), ordered.end(), [&](auto l, auto r) { return key(l) < key(r); }));
    return Json{{"x", result[0]}, {"y", result[1]}};
}
std::optional<std::string> GridMap::zone(XY p) const {
    for (auto &z : data.at("zones")) {
        int x = z.at("x"), y = z.at("y");
        if (x <= p[0] && p[0] < x + z.at("w").get<int>() && y <= p[1] && p[1] < y + z.at("h").get<int>())
            return z.at("name").get<std::string>();
    }
    return {};
}
std::vector<Cell> GridMap::route(Cell from, Cell to, const std::set<Cell> &blocked) const {
    if (!floor.contains(from) || !floor.contains(to))
        throw std::invalid_argument("Недоступная точка маршрута");
    std::deque<Cell> queue{from};
    std::map<Cell, Cell> parents{{from, from}};
    while (!queue.empty()) {
        auto here = queue.front();
        queue.pop_front();
        if (here == to) {
            std::vector<Cell> path;
            while (here != from) {
                path.push_back(here);
                here = parents.at(here);
            }
            std::reverse(path.begin(), path.end());
            return path;
        }
        for (auto next : neighbors(here))
            if (floor.contains(next) && !blocked.contains(next) && parents.try_emplace(next, here).second)
                queue.push_back(next);
    }
    return {};
}
std::pair<int, XY> GridMap::escape(Cell from, XY bomb, double radius) const {
    std::deque<Cell> queue;
    std::map<Cell, std::pair<int, XY>> goals;
    for (auto cell : floor) {
        auto p = center(cell);
        if (gap2(p, bomb) >= radius + unit) {
            goals[cell] = {0, p};
            queue.push_back(cell);
        }
    }
    while (!queue.empty()) {
        auto h = queue.front();
        queue.pop_front();
        auto [length, goal] = goals.at(h);
        if (h == from)
            return {length, goal};
        for (auto n : neighbors(h))
            if (floor.contains(n) && goals.try_emplace(n, length + int(unit), goal).second)
                queue.push_back(n);
    }
    throw std::invalid_argument("Недоступная позиция выхода");
}
bool GridMap::walk(Json &a, const Json &goal, double speed, const Json &fire, bool detour) const {
    auto pos = xy(a);
    auto from = cell(pos), to = cell(goal.get<XY>());
    auto origin = center(from);
    auto home = point(from);
    for (int i = 0; i < 2; i++)
        if (a.at(i ? "y" : "x").is_number_float())
            home[i] = origin[i];
    auto &path = a.at("path");
    if (a.at("dest") != Json(to) || path.empty()) {
        path = Json::array();
        for (auto step : route(from, to))
            path.push_back(point(step));
        if (pos != origin && (path.empty() || !clear(pos, path[0].get<XY>())))
            path.insert(path.begin(), home);
        a["dest"] = to;
        for (int i = 0; i < 2; i++)
            if (goal[i].is_number_float())
                a["dest"][i] = std::floor(goal[i].get<double>() / unit);
    }
    if (path.empty())
        return false;
    auto next = path[0].get<XY>();
    if (std::ranges::any_of(fire, [&](const Json &f) {
            double radius = f.at("radius");
            return gap2(next, xy(f)) < radius && gap2(pos, xy(f)) >= radius;
        })) {
        std::vector<Cell> alternate;
        if (detour) {
            std::set<Cell> blocked;
            for (auto c : floor)
                if (std::ranges::any_of(fire, [&](const Json &f) {
                        return gap2(center(c), xy(f)) < f.at("radius").get<double>();
                    }))
                    blocked.insert(c);
            alternate = route(from, to, blocked);
        }
        if (alternate.empty()) {
            a["status"] = "Пережидает огонь за укрытием";
            return false;
        }
        path = Json::array();
        if (pos != origin)
            path.push_back(home);
        for (auto c : alternate)
            path.push_back(point(c));
        next = path[0].get<XY>();
        a["status"] = "Обходит огонь";
    }
    a["heading"] = std::atan2(next[1] - pos[1], next[0] - pos[0]);
    for (int i = 0; i < 2; i++) {
        auto &v = a.at(i ? "y" : "x");
        double d = next[i] - pos[i];
        if (v.is_number_integer() && path[0][i].is_number_integer() && std::abs(d) < speed)
            v = int(next[i]);
        else
            v = round_decimal(pos[i] + std::clamp(d, -speed, speed), 3);
    }
    if (xy(a) == next)
        path.erase(path.begin());
    return true;
}
} // namespace esport
