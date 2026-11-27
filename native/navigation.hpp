#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <optional>
#include <utility>
#include <vector>

namespace esport {
using Point = std::array<double, 3>;
using Area = std::pair<std::int64_t, std::vector<Point>>;

// World-space polygons remain immutable for the lifetime of an installed map.
class NavSurfaces {
public:
    explicit NavSurfaces(std::vector<Area> areas);
    std::optional<std::int64_t> locate(const Point& point, double max_vertical) const;
    std::vector<std::optional<std::int64_t>> locate_many(
        const std::vector<Point>& points, double max_vertical) const;

private:
    using Sector = std::pair<double, double>;
    std::vector<Area> areas_;
    std::map<Sector, std::vector<std::size_t>> sectors_;
    // Wide polygons are tested directly to bound index memory.
    std::vector<std::size_t> wide_;
};
}
