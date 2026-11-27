#pragma once
#include "navigation.hpp"
#include "round_rules.hpp"
#include <map>
#include <set>
namespace esport {
using Cell = std::pair<int, int>;
using XY = std::array<double, 2>;
class GridMap {
  public:
    explicit GridMap(const Json &data);
    Cell cell(XY value) const;
    XY center(Cell p) const;
    Json point(Cell p) const;
    bool clear(XY a, XY b) const;
    bool sees(const Json &a, const Json &b) const;
    Json sound(XY source) const;
    std::optional<std::string> zone(XY p) const;
    std::vector<Cell> route(Cell from, Cell to, const std::set<Cell> &blocked = {}) const;
    std::pair<int, XY> escape(Cell from, XY bomb, double radius) const;
    bool walk(Json &a, const Json &goal, double speed, const Json &fire, bool detour) const;
    const Json data;
    const double unit, vision;

  private:
    std::set<Cell> floor;
    std::vector<Cell> ordered;
};
XY xy(const Json &a);
double gap2(XY a, XY b);
} // namespace esport
