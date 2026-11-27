#include "navigation.hpp"

#include <stdexcept>

int main() {
    using namespace esport;
    // Negative sector, wide polygon, stacked slope and shared height tie.
    const std::vector<Point> floor{{-256, 0, 0}, {65536, 0, 0}, {65536, 256, 0}};
    const std::vector<Point> slope{{0, 0, 0}, {256, 0, 16}, {0, 256, 0}};
    const std::vector<Point> queries{{-256, 0, 0}, {128, 1, 8}, {0, 0, 0}, {-257, 0, 0}};
    const std::vector<std::optional<std::int64_t>> expected{7, 3, 3, std::nullopt};
    for (int i = 0; i < 5000; ++i) {
        NavSurfaces nav({{7, floor}, {3, slope}});
        if (nav.locate_many(queries, 8) != expected) throw std::runtime_error("NAV mismatch");
    }
}
