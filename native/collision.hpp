#pragma once
#include "navigation.hpp"
#include "rays.hpp"

#include <optional>
#include <tuple>

namespace esport {
using Matrix = std::array<Point, 3>;
struct Primitive {
    Matrix inverse;
    Point translation, first, last, axis;
    double length, radius;
    Point low, high;
    unsigned mask, material;
};
using Impact = std::tuple<double, unsigned, std::optional<Point>>;

class CollisionWorld {
  public:
    CollisionWorld(std::shared_ptr<const TriangleScene> mesh, std::vector<unsigned short> materials,
                   std::vector<Primitive> shapes);
    std::optional<Impact> trace(const Point &source, const Point &target, unsigned channel,
                                bool terminal = false) const;
    std::vector<bool> visible(const std::vector<std::pair<Point, Point>> &segments) const;

  private:
    struct Node {
        Point low, high;
        unsigned mask{};
        std::size_t begin, end, left{}, right{};
    };
    std::shared_ptr<const TriangleScene> mesh_;
    std::vector<unsigned short> materials_;
    std::vector<Primitive> shapes_;
    std::vector<Node> nodes_;
    std::size_t build(std::size_t begin, std::size_t end);
};
} // namespace esport
