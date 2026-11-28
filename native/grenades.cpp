#include "grenades.hpp"
#include "coaching.hpp"
#include <algorithm>
#include <cmath>
#include <queue>

namespace esport {
namespace {
Point point(const Json &j) {
    return {j.at("x"), j.at("y"), j.value("z", 0.)};
}
double remaining(const Json &pulse, Tick now) {
    const Tick end = pulse.at("end"), hold = pulse.at("hold");
    return pulse.at("peak").get<double>() * std::clamp(double(end - now) / (end - hold), 0., 1.);
}
} // namespace
void count_utility(Json &w, const Json &owner, const std::string &metric, int amount) {
    auto &row = w.at("stats").at(owner.get<std::string>());
    row[metric] = row.value(metric, 0) + amount;
}
double flash_exposure(const Point &eye, double heading, const Point &burst, double radius) {
    const double d = distance(eye, burst);
    if (d >= radius)
        return 0;
    const double facing =
        d < .1 ? 1. : ((burst[0] - eye[0]) * std::cos(heading) + (burst[1] - eye[1]) * std::sin(heading)) / d;
    const double alignment = (.5 + .5 * std::clamp(facing, -1., 1.));
    return std::min(1., 1.35 * std::sqrt(1. - d / radius) * (.18 + .82 * alignment * alignment));
}
void receive_flash_warning(Json &actor, const Json &warning, const Json &sender, bool coordinated) {
    if (coordinated) {
        const auto id = sender.get<std::string>();
        actor["flashWarnings"][id] = warning;
    } else
        actor["flashWarning"] = warning;
}
void expose_player(Json &w, Json &a, const Json &f, double peak) {
    if (peak < .05)
        return;
    const Tick now = w.at("tick");
    const int duration = 3 + int(std::lround(44 * peak));
    auto &pulses = a["flashPulses"];
    pulses.push_back({{"owner", f.at("player")},
                      {"hostile", f.at("team") != a.at("team")},
                      {"peak", peak},
                      {"hold", now + int(12 * peak)},
                      {"end", now + duration}});
    auto &event = emit(w, "flash", a.at("name").get<std::string>() + " ослеплён", a.at("team"));
    event.update({{"player", a.at("id")}, {"owner", f.at("player")}, {"duration", duration}, {"peak", peak}});
    if (a.contains("mind") && f.at("player")==a.at("id") && peak >= .55)
        self_flash_emotion(w,a,event.at("id"));
    count_utility(w, f.at("player"),
                  f.at("team") != a.at("team")   ? "enemiesFlashed"
                  : f.at("player") == a.at("id") ? "selfFlashes"
                                                 : "alliesFlashed");
}
void impaired(Json &actor, Tick now) {
    const auto owner = actor.value("flashAssistOwner", Json(nullptr));
    actor["flashImpairedBy"] = owner;
    actor["flashImpairedAt"] = now;
}
bool assisted_by_flash(const Json &actor, Tick now) {
    if (actor.value("flashImpairedAt", Tick{-100}) < now - 1 || !actor.contains("flashPulses"))
        return false;
    const Json helper = actor.value("flashImpairedBy", Json(nullptr));
    double with = 1., without = 1.;
    for (const auto &p : actor.at("flashPulses")) {
        const double transmission = 1. - remaining(p, now);
        with *= transmission;
        if (p.at("owner") != helper)
            without *= transmission;
    }
    return !helper.is_null() && without - with >= .20;
}
void recover_vision(Json &w) {
    const Tick now = w.at("tick");
    for (auto &a : w.at("agents")) {
        auto pulses = a.find("flashPulses");
        if (pulses == a.end())
            continue;
        const bool alive = a.at("hp") != 0;
        pulses->erase(std::remove_if(pulses->begin(), pulses->end(),
                                     [&](const Json &p) { return !alive || p.at("end") <= now; }),
                      pulses->end());
        double transmission = 1., strongest = 0.;
        Json owner = nullptr;
        for (const auto &p : *pulses) {
            const auto level = remaining(p, now);
            transmission *= 1. - level;
            if (p.at("hostile") == true && level > strongest) {
                strongest = level;
                owner = p.at("owner");
            }
        }
        const double level = 1. - transmission;
        a["flashLevel"] = level;
        a["blind"] = level >= .78 ? now + 1 : now;
        a["flashAssistOwner"] = strongest >= .25 ? owner : Json(nullptr);
        if (!owner.is_null())
            count_utility(w, owner, "enemyBlindTicks");
        if (level == 0)
            a.erase("flashPulses");
    }
}
bool recognizes(const Json &a, const Point &p, Tick now) {
    const double level = a.value("flashLevel", 0.);
    if (level <= .01)
        return true;
    if (level >= .78)
        return false;
    auto eye = point(a);
    const double d = distance(eye, p), h = a.at("heading");
    const double dot = (p[0] - eye[0]) * std::cos(h) + (p[1] - eye[1]) * std::sin(h);
    return d <= 180 * (1. - level) && dot >= std::hypot(p[0] - eye[0], p[1] - eye[1]) * (.5 + .48 * level) &&
           (now + a.at("slot").get<int>()) % (1 + int(4 * level)) == 0;
}

// A bounded wave traverses connected floor samples once at detonation. Each
// local lobe has its own growth delay and is clipped against nearby solid walls.
void spread_volume(Json &f, const PhysicalNavigation *map, const GridMap *grid) {
    const Point origin = point(f);
    const double radius = f.at("radius"), spacing = radius / 2.6;
    const bool smoke = f.at("kind") == "Дым";
    std::queue<std::pair<Cell, Point>> queue;
    std::set<Cell> visited{{0, 0}};
    queue.push({{0, 0}, origin});
    auto &cells = f["lobes"] = Json::array();
    auto clear = [&](const Point &p, const Point &q) {
        return map ? !map->hit(p, q, 1, 16, 16) : grid->clear({p[0], p[1]}, {q[0], q[1]});
    };
    while (!queue.empty()) {
        auto [index, p] = queue.front();
        queue.pop();
        double r = spacing * .82;
        for (Cell dir : {Cell{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) {
            Cell next{index.first + dir.first, index.second + dir.second};
            Point q{p[0] + dir.first * spacing, p[1] + dir.second * spacing, p[2]};
            if (!clear(p, q)) {
                if (map) {
                    auto hit = map->hit(p, q, 1, 16, 16);
                    if (hit)
                        r = std::min(r, spacing * std::get<0>(*hit));
                } else
                    r = std::min(r, spacing * .45);
                continue;
            }
            if (visited.contains(next) || std::hypot(next.first, next.second) > 2.25)
                continue;
            if (map) {
                auto top = q, bottom = q;
                top[2] += 4;
                bottom[2] -= 6;
                auto ground = map->hit(top, bottom, 8, 0, 0);
                if (!ground)
                    continue;
                q[2] = top[2] - 10 * std::get<0>(*ground);
                if (!clear(p, q))
                    continue;
            }
            visited.insert(next);
            queue.push({next, q});
        }
        if (r > .1)
            cells.push_back({{"p", p},
                             {"size", r},
                             {"reach", 0.},
                             {"clearUntil", 0},
                             {"delay", int(std::hypot(index.first, index.second) * (smoke ? 2 : 4))}});
    }
}
void append_volume(const Json &f, std::vector<Hazard> &out) {
    if (!f.contains("lobes")) {
        out.emplace_back(point(f), f.at("radius"));
        return;
    }
    for (const auto &c : f.at("lobes"))
        if (c.at("reach") > 0)
            out.emplace_back(c.at("p").get<Point>(), c.at("reach"));
}
bool crosses_volume(const Json &f, const Point &from, const Point &to) {
    if (!near_segment(from, to, point(f), f.at("radius").get<double>() * (f.contains("lobes") ? 1.3 : 1.)))
        return false;
    if (!f.contains("lobes"))
        return true;
    return std::ranges::any_of(f.at("lobes"), [&](const Json &c) {
        return c.at("reach") > 0 && near_segment(from, to, c.at("p").get<Point>(), c.at("reach"));
    });
}
void disturb_smoke(Json &w, const Point &from, const Point &to, bool blast, const Json &owner) {
    const Tick now = w.at("tick");
    bool disturbed = false;
    for (auto &f : w.at("effects")) {
        if (f.at("kind") != "Дым" || !f.contains("lobes") ||
            !near_segment(from, to, point(f), f.at("radius").get<double>() * 1.3 + (blast ? 18 : 0)))
            continue;
        Tick review = f.value("volumeReview", now + 1);
        for (auto &c : f.at("lobes")) {
            if (c.at("reach") <= 0 ||
                !near_segment(from, to, c.at("p").get<Point>(), blast ? 18. : c.at("reach").get<double>()))
                continue;
            c["clearUntil"] = now + (blast ? 16 : 2);
            review = std::min(review, c.at("clearUntil").get<Tick>());
            c["reach"] = 0.;
            disturbed = true;
        }
        f["volumeReview"] = review;
    }
    if (disturbed)
        count_utility(w, owner, blast ? "smokesOpened" : "smokeShots");
}
void update_volumes(Json &w, const PhysicalNavigation *map, const GridMap *grid) {
    const Tick now = w.at("tick");
    auto &effects = w.at("effects");
    for (auto &f : effects) {
        const bool smoke = f.at("kind") == "Дым";
        if ((!smoke && f.at("kind") != "Огонь") || now < f.at("land"))
            continue;
        if (!f.contains("lobes"))
            spread_volume(f, map, grid);
        // Mature cells need no per-tick work until fading or a hole closes.
        if (now < f.value("volumeReview", Tick{0}))
            continue;
        Tick review = smoke ? f.at("end").get<Tick>() - 14 : f.at("end").get<Tick>();
        for (auto &c : f.at("lobes")) {
            const Tick age = now - f.at("land").get<Tick>() - c.at("delay").get<int>();
            if (age < (smoke ? 6 : 4))
                review = now + 1;
            if (c.at("clearUntil") > now)
                review = std::min(review, c.at("clearUntil").get<Tick>());
            double density = std::clamp((age + 1) / (smoke ? 6. : 4.), 0., 1.);
            if (smoke)
                density *= std::clamp((f.at("end").get<Tick>() - now) / 14., 0., 1.);
            c["reach"] =
                c.value("out", false) || c.at("clearUntil") > now ? 0. : c.at("size").get<double>() * density;
        }
        f["volumeReview"] = std::max(now + 1, review);
    }
    for (const auto &f : effects)
        if (f.at("kind") == "HE" && f.at("land") == now)
            disturb_smoke(w, point(f), point(f), true, f.at("player"));
    for (auto &f : effects) {
        if (f.at("kind") != "Огонь" || !f.contains("lobes"))
            continue;
        for (const auto &smoke : effects) {
            if (smoke.at("kind") != "Дым" || !smoke.contains("lobes") ||
                distance(point(f), point(smoke)) > 50)
                continue;
            const bool core = crosses_volume(smoke, point(f), point(f));
            bool quenched = false;
            for (auto &cell : f.at("lobes")) {
                if (cell.value("out", false))
                    continue;
                const Point p = cell.at("p");
                if (!core && !crosses_volume(smoke, p, p))
                    continue;
                cell["reach"] = 0.;
                cell["out"] = true;
                quenched = true;
            }
            if (quenched && !f.value("quenched", false)) {
                f["quenched"] = true;
                count_utility(w, smoke.at("player"), "firesQuenched");
                emit(w, "extinguish", "Дым тушит огонь", smoke.at("team"))
                    .update({{"player", smoke.at("player")}, {"x", f.at("x")}, {"y", f.at("y")}});
            }
        }
    }
}
} // namespace esport
