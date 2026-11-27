#include "perception.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace esport {
namespace {
bool in_smoke(const Point &a, const Point &b, const Hazard &fog) {
    const auto &[p, radius] = fog;
    const Point delta{b[0] - a[0], b[1] - a[1], b[2] - a[2]};
    const auto [dx, dy, dz] = delta;
    const double length = dx * dx + dy * dy + dz * dz;
    const double ratio =
        length ? std::clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy + (p[2] - a[2]) * dz) / length, 0., 1.)
               : 0.;
    const Point nearest{a[0] + ratio * dx, a[1] + ratio * dy, a[2] + ratio * dz};
    return distance(nearest, p) <= radius;
}
double resistance(const std::string &name) {
    if (name == "glass")
        return .08;
    if (name == "cardboard")
        return .09;
    if (name == "plastic")
        return .16;
    if (name == "wood" || name == "wood_panel")
        return .25;
    if (name == "metalgrate")
        return .18;
    return -1.;
}
} // namespace

MapSensors::MapSensors(std::shared_ptr<const PhysicalNavigation> map, std::vector<std::string> materials)
    : map_(std::move(map)), materials_(std::move(materials)) {
    if (!map_)
        throw std::invalid_argument("Missing physical map");
}

std::vector<std::vector<std::size_t>> MapSensors::observe(const std::vector<Observer> &players,
                                                          const std::vector<Hazard> &smoke) const {
    std::vector<std::vector<std::size_t>> seen(players.size());
    for (std::size_t i = 0; i < players.size(); ++i) {
        const auto &observer = players[i];
        if (observer.blind)
            continue;
        const double dx = std::cos(observer.heading), dy = std::sin(observer.heading);
        const auto &a = observer.position;
        for (std::size_t j = 0; j < players.size(); ++j) {
            if (players[j].attack == observer.attack)
                continue;
            const auto &b = players[j].position;
            const double vx = b[0] - a[0], vy = b[1] - a[1], dot = vx * dx + vy * dy;
            if (dot < 0 || 4 * dot * dot < vx * vx + vy * vy)
                continue;
            if (map_->hit(a, b, 1, 64, 64, true))
                continue;
            if (!std::ranges::any_of(smoke, [&](const auto &fog) { return in_smoke(a, b, fog); }))
                seen[i].push_back(j);
        }
    }
    return seen;
}

std::vector<Heard> MapSensors::hear(const Point &source, double radius,
                                    const std::vector<Listener> &guards) const {
    if (!std::isfinite(radius) || !std::ranges::all_of(source, [](double n) { return std::isfinite(n); }))
        throw std::invalid_argument("Invalid audio source");
    std::vector<Heard> cues;
    for (std::size_t i = 0; i < guards.size(); ++i) {
        const auto &listener = guards[i];
        if (!listener.eligible)
            continue;
        const auto &pos = listener.position;
        if (!std::isfinite(listener.reading) ||
            !std::ranges::all_of(pos, [](double n) { return std::isfinite(n); }))
            throw std::invalid_argument("Invalid audio listener");
        const double d = distance(pos, source);
        if (d > radius || d < 1)
            continue;
        double transmission = 1.;
        if (const auto obstruction = map_->hit(pos, source, 4, 48, 48)) {
            const auto &material = materials_.at(std::get<1>(*obstruction));
            transmission =
                (material == "wood" || material == "glass" || material == "metalgrate") ? .70 : .47;
        }
        const double reach = radius * transmission * (.78 + listener.reading / 460.);
        if (d + .8 * std::abs(source[2] - pos[2]) > reach)
            continue;
        const double theta = std::atan2(source[1] - pos[1], source[0] - pos[0]);
        const int sector = int(std::nearbyint(theta * 8 / (2 * std::numbers::pi)));
        constexpr std::array<std::array<int, 2>, 8> directions{
            {{1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}}};
        const auto [dx, dy] = directions[(sector + 8) % 8];
        double band = d < 25 ? 14 : (d < 62 ? 43 : 83);
        const double step = band / std::hypot(dx, dy);
        cues.push_back({i, {pos[0] + dx * step, pos[1] + dy * step, pos[2]}, .35 + .45 * (1 - d / reach)});
    }
    return cues;
}

double MapSensors::shot_transmission(const Point &start, const Point &end, double power) const {
    const double length = distance(start, end);
    if (!length)
        return 1.;
    std::map<std::string, double> layers;
    double transmission = 1., offset = 0.;
    while (offset < 1) {
        Point origin;
        for (int i = 0; i < 3; ++i)
            origin[i] = start[i] + (end[i] - start[i]) * offset;
        auto hit = map_->hit(origin, end, 4, 56, 56);
        if (!hit)
            break;
        const double at = offset + (1 - offset) * std::get<0>(*hit);
        const auto &material = materials_.at(std::get<1>(*hit));
        const double r = resistance(material);
        if (r < 0)
            return 0.;
        if (const auto open = layers.find(material); open != layers.end()) {
            double width = (at - open->second) * length;
            transmission -= r * width / std::max(.1, power);
            layers.erase(open);
        } else {
            layers[material] = at;
            transmission -= r * .5 / std::max(.1, power);
        }
        if (transmission <= 0)
            return 0.;
        offset = at + std::max(1e-6, .002 / length);
    }
    return transmission;
}
} // namespace esport
