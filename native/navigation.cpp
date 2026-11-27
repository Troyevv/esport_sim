#include "navigation.hpp"

#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>

namespace esport {
namespace {
double sector(double value) { return std::floor(value / 256.0); }

bool finite(const Point& p) {
    return std::all_of(p.begin(), p.end(), [](double x) { return std::isfinite(x); });
}

std::optional<double> surface_height(const std::vector<Point>& corners, double x, double y) {
    const auto [ax, ay, az] = corners.front();
    for (std::size_t i = 1; i + 1 < corners.size(); ++i) {
        const auto [bx, by, bz] = corners[i];
        const auto [cx, cy, cz] = corners[i + 1];
        const double det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
        if (std::abs(det) < 1e-8) continue;
        const double u = ((x - ax) * (cy - ay) - (y - ay) * (cx - ax)) / det;
        const double v = ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / det;
        if (std::min({u, v, 1 - u - v}) >= -1e-7)
            return az + u * (bz - az) + v * (cz - az);
    }
    return std::nullopt;
}
}

NavSurfaces::NavSurfaces(std::vector<Area> areas) : areas_(std::move(areas)) {
    std::set<std::int64_t> ids;
    for (std::size_t i = 0; i < areas_.size(); ++i) {
        const auto& [id, corners] = areas_[i];
        if (!ids.insert(id).second || corners.size() < 3)
            throw std::invalid_argument("Expected a unique area ID and at least three corners");
        Point lo = corners.front(), hi = lo;
        for (const auto& p : corners) {
            if (!finite(p)) throw std::invalid_argument("Non-finite NAV corner");
            for (int axis = 0; axis < 2; ++axis) {
                lo[axis] = std::min(lo[axis], p[axis]);
                hi[axis] = std::max(hi[axis], p[axis]);
            }
        }
        const double x = sector(lo[0]), y = sector(lo[1]);
        const double width = sector(hi[0]) - x + 1, height = sector(hi[1]) - y + 1;
        if (width * height > 256) {
            wide_.push_back({i, {x, y}, {sector(hi[0]), sector(hi[1])}});
        } else {
            for (int dx = 0; dx < width; ++dx)
                for (int dy = 0; dy < height; ++dy)
                    sectors_[{x + dx, y + dy}].push_back(i);
        }
    }
}

std::optional<std::int64_t> NavSurfaces::locate(const Point& p, double max_vertical) const {
    if (!finite(p) || !std::isfinite(max_vertical))
        throw std::invalid_argument("Non-finite NAV query");
    std::optional<std::pair<double, std::int64_t>> best;
    auto consider = [&](std::size_t index) {
        const auto& [id, corners] = areas_[index];
        if (auto z = surface_height(corners, p[0], p[1])) {
            auto candidate = std::pair{std::abs(p[2] - *z), id};
            if (candidate.first <= max_vertical && (!best || candidate < *best))
                best = candidate;
        }
    };
    const Sector key{sector(p[0]), sector(p[1])};
    const auto cell = sectors_.find(key);
    if (cell != sectors_.end()) {
        for (auto index : cell->second) consider(index);
    }
    for (const auto& entry : wide_) {
        if (entry.low.first <= key.first && key.first <= entry.high.first &&
            entry.low.second <= key.second && key.second <= entry.high.second)
            consider(entry.index);
    }
    if (best) return best->second;
    return std::nullopt;
}

std::vector<std::optional<std::int64_t>> NavSurfaces::locate_many(
    const std::vector<Point>& points, double max_vertical) const {
    std::vector<std::optional<std::int64_t>> result;
    result.reserve(points.size());
    for (const auto& p : points) result.push_back(locate(p, max_vertical));
    return result;
}
}
