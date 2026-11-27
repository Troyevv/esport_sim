#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <utility>
#include <vector>

namespace esport {
using Point = std::array<double, 3>;
using Area = std::pair<std::int64_t, std::vector<Point>>;

double round_decimal(double value, int digits);
double sum3(double a, double b, double c);
double distance(const Point &a, const Point &b);
std::optional<double> surface_height(const std::vector<Point> &corners, double x, double y);

// World-space polygons remain immutable for the lifetime of an installed map.
class NavSurfaces {
  public:
    explicit NavSurfaces(std::vector<Area> areas);
    std::optional<std::int64_t> locate(const Point &point, double max_vertical) const;
    std::optional<std::pair<std::int64_t,double>> locate_with_height(const Point& point,double max_vertical) const;
    std::vector<std::optional<std::int64_t>> locate_many(const std::vector<Point> &points,
                                                         double max_vertical) const;

  private:
    using Sector = std::pair<double, double>;
    std::vector<Area> areas_;
    std::map<Sector, std::vector<std::size_t>> sectors_;
    // Wide polygons are tested directly to bound index memory.
    struct WideArea {
        std::size_t index;
        Sector low, high;
    };
    std::vector<WideArea> wide_;
};
} // namespace esport
