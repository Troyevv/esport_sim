#pragma once
#include "agent_turn.hpp"
#include <algorithm>
#include <cmath>

namespace esport {
inline bool active(const Json &obj, const std::string &key) {
    if (!obj.contains(key))
        return false;
    const auto &v = obj.at(key);
    if (v.is_boolean())
        return v.get<bool>();
    if (v.is_number())
        return v.get<double>() != 0;
    if (v.is_string())
        return !v.get_ref<const std::string &>().empty();
    return !v.empty();
}
inline Json coordinate(const Point &p) { return Json{{"x", p[0]}, {"y", p[1]}, {"z", p[2]}}; }
inline Json grenade_intent(const Point &p, const std::string &kind, const std::string &purpose = {}) {
    auto aim = coordinate(p);
    aim["utility"] = kind;
    if (!purpose.empty())
        aim["purpose"] = purpose;
    return Json::array({"throw", aim});
}
inline bool in_range_fov(const Json &a, const Point &p) {
    auto dx = p[0] - a.at("x").get<double>(), dy = p[1] - a.at("y").get<double>(),
         h = a.at("heading").get<double>();
    double dot = dx * std::cos(h) + dy * std::sin(h);
    return dot >= 0 && 4 * dot * dot >= dx * dx + dy * dy;
}
inline bool member_of(const Json &xs, const Json &x) {
    return std::find(xs.begin(), xs.end(), x) != xs.end();
}
inline std::vector<Point> nearby_points(const PhysicalNavigation &nav, const Point &center, double radius) {
    std::vector<Point> out;
    for (auto &[id, p] : nav.centers())
        if (distance(p, center) < radius)
            out.push_back(p);
    return out;
}
inline std::optional<Point> first_reachable(const PhysicalNavigation &nav, const Point &start,
                                            const std::vector<Point> &choices,
                                            std::optional<AreaId> area = {}) {
    if (!area)
        area = nav.locate(start);
    if (!area)
        return {};
    for (auto &p : choices)
        if (auto to = nav.locate(p); to && nav.path(*area, start, *to, p, {}))
            return p;
    return {};
}
inline void heading_to(Json &a, const Point &p) {
    a["heading"] = std::atan2(p[1] - a.at("y").get<double>(), p[0] - a.at("x").get<double>());
}
inline bool visual(const Json &r) { return r.at("source") == "Зрение" || r.at("source") == "Радио"; }
inline double heading_gap(const Point &from, const Point &to) {
    return std::atan2(to[1] - from[1], to[0] - from[0]);
}
inline bool outside_bearing(const Point &q, const Json &bearing) {
    if (bearing.empty())
        return false;
    auto b = bearing.get<std::array<double, 4>>();
    auto x = q[0] - b[0], y = q[1] - b[1];
    return x * b[2] + y * b[3] < std::abs(x * b[3] - y * b[2]);
}
} // namespace esport
