#include "grenades.hpp"
#include "objectives.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace esport {
namespace {
Point xyz(const Json &j) { return {j.at("x"), j.at("y"), j.value("z", 0.)}; }
Point sub(const Point &a, const Point &b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
double dot(const Point &a, const Point &b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
Point cross(const Point &a, const Point &b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
bool contains(const std::vector<Triangle> &triangles, const Point &p) {
    double angle = 0.;
    for (const auto &[a, b, c] : triangles) {
        Point u = sub(a, p), v = sub(b, p), w = sub(c, p);
        Point normal = cross(sub(b, a), sub(c, a));
        double squared = dot(normal, normal);
        if (squared < 1e-14)
            continue;
        double det = dot(u, cross(v, w));
        if (std::abs(det) <= 1e-7 * std::sqrt(squared) &&
            std::min({dot(cross(u, v), normal), dot(cross(v, w), normal), dot(cross(w, u), normal)}) >=
                -1e-8 * squared)
            return true;
        double lu = distance(a, p), lv = distance(b, p), lw = distance(c, p);
        auto denom = lu * lv * lw + dot(u, v) * lw + dot(v, w) * lu + dot(w, u) * lv;
        angle += 2 * std::atan2(det, denom);
    }
    return std::abs(angle) > 2 * std::numbers::pi;
}
Json &agent(Json &roster, const Json &id) {
    for (auto &a : roster)
        if (a.at("id") == id)
            return a;
    throw std::invalid_argument("Неизвестный участник действия");
}
bool facing(const Json &a, const Json &b) {
    double x = b.at("x").get<double>() - a.at("x").get<double>(),
           y = b.at("y").get<double>() - a.at("y").get<double>();
    double h = a.at("heading"), d = x * std::cos(h) + y * std::sin(h);
    return d >= 0 && 4 * d * d >= x * x + y * y;
}
} // namespace
Objectives::Objectives(std::shared_ptr<const PhysicalNavigation> map, SiteData data)
    : map_(std::move(map)), costs_(std::move(data.costs)), samples_(std::move(data.samples)),
      ingress_(std::move(data.ingress)) {
    if (!map_)
        throw std::invalid_argument("Missing physical map");
    for (const std::string site : {"A", "B"}) {
        if (!data.solids.contains(site) || data.solids.at(site).empty() || !costs_.contains(site) ||
            !samples_.contains(site))
            throw std::invalid_argument("Incomplete bomb site");
        for (auto &triangles : data.solids.at(site)) {
            if (triangles.empty())
                throw std::invalid_argument("Empty site geometry");
            Solid solid{triangles[0][0], triangles[0][0], std::move(triangles)};
            for (const auto &face : solid.triangles)
                for (const auto &p : face)
                    for (int j = 0; j < 3; ++j) {
                        if (!std::isfinite(p[j]))
                            throw std::invalid_argument("Invalid bomb site coordinate");
                        solid.low[j] = std::min(solid.low[j], p[j]);
                        solid.high[j] = std::max(solid.high[j], p[j]);
                    }
            volumes_[site].push_back(std::move(solid));
        }
    }
}

std::optional<std::string> Objectives::site_at(const Point &position) const {
    if (grid_)
        return grid_->zone({position[0], position[1]});
    auto p = map_->world(position);
    p[2] += 1;
    for (const auto &[name, solids] : volumes_)
        for (const auto &solid : solids) {
            bool bounded = true;
            for (int j = 0; j < 3; ++j)
                if (p[j] < solid.low[j] - 1e-6 || p[j] > solid.high[j] + 1e-6)
                    bounded = false;
            if (bounded && contains(solid.triangles, p))
                return name;
        }
    return std::nullopt;
}

void Objectives::hear_plant(Json &w, const Point &source) const {
    for (auto &a : w.at("agents")) {
        if (a.at("team") != "CT" || a.at("hp") == 0)
            continue;
        const auto pos = xyz(a);
        double d = distance(pos, source);
        if (d > 55 || (d > 26 && map_->hit(pos, source, 1, 64, 34)))
            continue;
        const auto [dx, dy] = sound_direction(pos, source);
        std::optional<std::pair<double, std::string>> best;
        for (const auto &[site, costs] : costs_) {
            bool audible_site = std::ranges::any_of(samples_.at(site), [&](const auto &p) {
                double vx = p[0] - pos[0], vy = p[1] - pos[1];
                return vx * dx + vy * dy >= std::abs(vx * dy - vy * dx);
            });
            if (!audible_site)
                continue;
            auto it = costs.find(a.at("navArea").get<AreaId>());
            auto candidate =
                std::pair{it == costs.end() ? std::numeric_limits<double>::infinity() : it->second, site};
            if (!best || candidate < *best)
                best = candidate;
        }
        if (best)
            a["plantCue"] = Json{{"tick", w.at("tick")},
                                 {"site", best->second},
                                 {"bearing", Json::array({a.at("x"), a.at("y"), dx, dy})}};
    }
}
void Objectives::interact(Json &w, const Json &cfg, Json &a, const std::string &kind, Json site) const {
    auto pos = xyz(a);
    auto &bomb = w.at("bomb");
    bool plant = kind == "plant";
    if (map_ && plant) {
        auto label = site_at(pos);
        if (!label || bomb.at("carrier") != a.at("id"))
            return;
        site = *label;
    } else if (map_ && (distance(pos, xyz(bomb)) > 6 || map_->hit(pos, xyz(bomb), 1, 64, 5)))
        return;
    Tick now = w.at("tick");
    const auto &rules = cfg.at("rules");
    auto &action = w.at("action");
    if (action.is_null()) {
        auto duration = rules.at(plant ? "plant" : a.at("kit") == true ? "kitDefuse" : "defuse").get<int>();
        action = Json{{"player", a.at("id")},
                      {"kind", kind},
                      {"site", site},
                      {"start", now},
                      {"end", plus_ticks(now, duration)}};
        if (map_ && plant)
            hear_plant(w, pos);
        else if (map_) {
            auto p = xyz(bomb);
            for (auto &t : w.at("agents"))
                if (t.at("hp") != 0 && t.at("team") == "T") {
                    auto q = xyz(t);
                    auto d = distance(q, p);
                    if (d < 26 || (d < 55 && !map_->hit(q, p, 1, 64, 12)))
                        t["heardUse"] = now;
                }
        }
        a["status"] = plant ? "Ставит C4" : "Обезвреживает";
        emit(w, kind + "_start", a.at("name").get<std::string>() + " · " + a.at("status").get<std::string>(),
             a.at("team"))
            .update(Json{{"player", a.at("id")}});
    }
    if (action.at("player") != a.at("id") || now < action.at("end").get<Tick>())
        return;
    if (action.at("kind") == "plant") {
        bomb.update(
            Json{{"carrier", nullptr}, {"site", action.at("site")}, {"x", a.at("x")}, {"y", a.at("y")}});
        if (map_)
            bomb["z"] = a.at("z");
        w["phase"] = "planted";
        w["deadline"] = plus_ticks(now, rules.at("fuse"));
        action = nullptr;
        pay(w, a, rules.at("planter"), "Установка C4", rules.at("cap"));
        emit(w, "plant", a.at("name").get<std::string>() + " установил C4")
            .update(Json{{"player", a.at("id")}});
    } else {
        pay(w, a, rules.at("defuser"), "Обезвреживание C4", rules.at("cap"));
        emit(w, "defuse", a.at("name").get<std::string>() + " обезвредил C4")
            .update(Json{{"player", a.at("id")}});
        settle_round(w, cfg, "CT", "Обезвреживание");
    }
}

void Objectives::resolve(Json &w, const Json &cfg, const Json &order) const {
    const Tick now = w.at("tick");
    auto &roster = w.at("agents");
    auto &action = w.at("action");
    auto &bomb = w.at("bomb");
    if (!action.is_null()) {
        auto &actor = agent(roster, action.at("player"));
        bool continued = actor.at("hp") != 0 && std::ranges::any_of(order, [&](const Json &intent) {
                             return intent.at("actor") == actor.at("id") && intent.at("kind") == "objective";
                         });
        if (!continued) {
            emit(w, "interrupt", "Действие с C4 прервано", actor.at("team"))
                .update(Json{{"player", actor.at("id")}});
            action = nullptr;
        }
    }
    std::map<std::string, std::vector<std::string>> living{{"T", {}}, {"CT", {}}};
    for (const auto &a : roster)
        if (a.at("hp") != 0)
            living.at(a.at("team")).push_back(a.at("id"));
    auto &t = living.at("T");
    auto &ct = living.at("CT");
    bool live = w.at("phase") == "live", expired = now >= w.at("deadline").get<Tick>();
    if (!live && expired) {
        emit(w, "explode", "C4 взорвалась");
        for (auto &a : roster)
            if (a.at("hp") != 0) {
                const double damage =
                    std::max(0., std::nearbyint(370 * (1 - distance(xyz(a), xyz(bomb)) /
                                                               cfg.at("blastRadius").get<double>())));
                if (damage)
                    apply_impact(w, cfg, a, a, damage, "C4", "blast");
            }
        settle_round(w, cfg, "T", "Взрыв C4");
    } else if (ct.empty() && t.empty() && live) {
        auto winning_side = agent(roster, w.at("kills").back().at("target")).at("team").get<std::string>();
        settle_round(w, cfg, winning_side, "Устранение");
    } else if (ct.empty())
        settle_round(w, cfg, "T", "Устранение");
    else if (t.empty() && live)
        settle_round(w, cfg, "CT", "Устранение");
    else if (expired && live)
        settle_round(w, cfg, "CT", "Время");
    else {
        for (auto side : {"T", "CT"}) {
            const auto &team = living.at(side);
            auto other = std::string(side) == "T" ? "CT" : "T";
            if (team.size() == 1 && !living.at(other).empty() && !w.at("clutch").contains(side))
                w.at("clutch")[side] = team[0];
        }
        for (const auto &item : order) {
            auto &a = agent(roster, item.at("actor"));
            if (a.at("hp") == 0)
                continue;
            if (item.at("kind") == "objective" && !action.is_null())
                interact(w, cfg, a, action.at("kind").get<std::string>());
            else if (item.at("kind") == "defuse" && w.at("phase") == "planted")
                interact(w, cfg, a, "defuse");
            else if (item.at("kind") == "plant" && w.at("phase") == "live")
                interact(w, cfg, a, "plant", item.at("target"));
            if (w.at("phase") == "result" || w.at("phase") == "finished")
                break;
        }
    }
    // Settlement can append a top-level history entry. Reacquire roster references.
    auto &agents = w.at("agents");
    for (auto &a : agents) {
        auto &visible = a.at("visible");
        visible.erase(std::remove_if(visible.begin(), visible.end(),
                                     [&](const Json &id) {
                                         const auto &b = agent(agents, id);
                                         if (a.at("hp") == 0 || b.at("hp") == 0 || a.at("blind") > now ||
                                             (grid_ ? !grid_->sees(a, b)
                                                    : (!facing(a, b) ||
                                                       bool(map_->hit(xyz(a), xyz(b), 1, 64, 64)))))
                                             return true;
                                         return std::ranges::any_of(w.at("effects"), [&](const auto &f) {
                                             return f.at("kind") == "Дым" && f.at("land") <= now &&
                                                    crosses_volume(f, xyz(a), xyz(b));
                                         });
                                     }),
                      visible.end());
    }
}
std::optional<std::string> Objectives::reported_site(const Point &p) const {
    if (grid_)
        return grid_->zone({p[0], p[1]});
    auto area = map_->locate(p);
    if (!area)
        return std::nullopt;
    auto cost = [&](const std::string &site) {
        const auto &c = costs_.at(site);
        auto it = c.find(*area);
        return it == c.end() ? std::numeric_limits<double>::infinity() : it->second;
    };
    double a = cost("A"), b = cost("B");
    if (std::min(a, b) <= 80 * map_->unit() && std::abs(b - a) > 8 * map_->unit())
        return a < b ? "A" : "B";
    return std::nullopt;
}
} // namespace esport
