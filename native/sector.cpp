#include "agent_helpers.hpp"
#include <bit>
#include <limits>
namespace esport {
namespace {
bool facing(const Point &origin, const Point &watch, const Point &p) {
    double dx = watch[0] - origin[0], dy = watch[1] - origin[1], x = p[0] - origin[0], y = p[1] - origin[1];
    return dx * x + dy * y >= .5 * std::hypot(dx, dy) * std::hypot(x, y);
}
double expected(const Json &report, Tick age, int reading) {
    if (age <= 0 || !active(report, "direction"))
        return 0;
    age = std::min<Tick>(age, 24);
    auto data = report.value("motionHistory", Json::object())
                    .value(std::to_string(std::bit_width(unsigned(age)) - 1), Json::array({0, 0}));
    auto supported = double(std::min(age, report.value("motionRun", Tick{1}))) / age;
    double fraction = (supported + data[0].get<double>()) / (1 + data[1].get<int>());
    return std::min(2., report.value("speed", 0.)) * age * (1 + (fraction - 1) * reading / 100);
}
bool entry(const OpeningMap &map, const Point &p, const std::string &wanted) {
    auto area = map.objectives().map().locate(p);
    if (!area)
        return false;
    auto any = [&](const std::string &site) {
        for (auto &sequence : map.profile().at(site))
            for (auto it = sequence.end() - std::min<std::size_t>(2, sequence.size()); it != sequence.end();
                 ++it) {
                const auto &ids = map.layout().places.at(it->get<std::string>());
                if (std::find(ids.begin(), ids.end(), *area) != ids.end())
                    return true;
            }
        return false;
    };
    return any(wanted) && !any(wanted == "A" ? "B" : "A");
}
} // namespace
Point AgentTurn::anticipated(const Json &report) const {
    const auto &nav = arena.objectives().map();
    auto pos = actor_point(report);
    if (!visual(report) || !active(report, "direction"))
        return pos;
    auto d = expected(report, now - report.at("tick").get<Tick>(), skills.at("game_reading"));
    if (!d)
        return pos;
    auto dir = report.at("direction").get<Point>(), q = pos;
    for (int i = 0; i < 3; ++i)
        q[i] += dir[i] * d;
    return nav.hit(pos, q, 1, 48, 48) ? pos : q;
}
Json &AgentTurn::attention(Point &focus) {
    const auto &nav = arena.objectives().map();
    auto *order = &const_cast<Json &>(assignment(plan, a, squad));
    auto &home = plan.at("orders").at("slots").at(slot);
    auto pos = actor_point(a);
    auto &intel = a.at("knowledge");
    if (home.contains("screen") && order == &home.at("screen")) {
        bool breached = false, recent = false;
        for (auto &r : intel) {
            auto age = now - r.at("tick").get<Tick>();
            recent |= r.at("source") == "Зрение" && age < 15;
            auto q = actor_point(r);
            if (age < 35 && visual(r) &&
                distance(q, home.at("hold").get<Point>()) < distance(q, order->at("watch").get<Point>()) &&
                arena.objectives().reported_site(q) == home.at("site").get<std::string>())
                breached = true;
        }
        if (distance(pos, order->at("hold").get<Point>()) < 5 && !order->contains("checkedAt"))
            (*order)["checkedAt"] = now;
        if (breached || active(a, "plantCue") || a.at("reloadAt") != 0 || a.at("hp") < 35 ||
            now - plan.at("start").get<Tick>() > 190 || recent ||
            (order->contains("checkedAt") &&
             now - order->at("checkedAt").get<Tick>() >= 12 + skills.at("map_control").get<int>() / 3)) {
            a["leftScreen"] = true;
            order = &home;
        }
    }
    auto token = Json::array({order->at("site"), order->at("hold"), order->at("watch")});
    if (active(a, "sectorReview") && a.at("sectorReview").at("token") == token &&
        now < a.at("sectorReview").at("next").get<Tick>()) {
        focus = a.at("sectorReview").at("focus").get<Point>();
        return *order;
    }
    auto hold = order->at("hold").get<Point>(), watch = order->at("watch").get<Point>();
    std::string site = order->at("site");
    Reports reports;
    for (auto &r : intel) {
        auto age = now - r.at("tick").get<Tick>();
        if (age > 0 && age < 30)
            reports.push_back(&r);
    }
    auto rank = [](const Json *r) {
        return std::pair{!active(*r, "carryingC4"), -r->at("tick").get<Tick>()};
    };
    std::stable_sort(reports.begin(), reports.end(), [&](auto l, auto r) { return rank(l) < rank(r); });
    bool chosen = false;
    for (auto r : reports) {
        auto last = actor_point(*r), point = anticipated(*r);
        auto age = now - r->at("tick").get<Tick>();
        if (r->at("source") == "Зрение" && age <= 12 && !nav.hit(pos, point, 1, 64, 64)) {
            focus = point;
            chosen = true;
            break;
        }
        if (r->at("source") == "Граната" || distance(last, hold) > 65)
            continue;
        auto observed = arena.objectives().reported_site(last);
        if (observed != site && (observed || (!facing(hold, watch, point) && !entry(arena, last, site))))
            continue;
        if (r->at("source") == "Слух" && age > 12)
            continue;
        std::optional<std::tuple<bool, double, int>> best;
        for (auto m : squad) {
            if (m->at("reloadAt") != 0 || m->at("blind") > now ||
                (!m->at("visible").empty() && !member_of(m->at("visible"), r->at("id"))))
                continue;
            auto &job = assignment(plan, *m, squad);
            if (job.at("site") != site || nav.hit(actor_point(*m), point, 1, 64, 64))
                continue;
            auto key = std::tuple{!facing(job.at("hold"), job.at("watch"), point),
                                  distance(actor_point(*m), point), m->at("slot").get<int>()};
            if (!best || key < *best)
                best = key;
        }
        if (best && std::get<2>(*best) == slot) {
            focus = point;
            chosen = true;
            break;
        }
    }
    if (!chosen) {
        std::vector<Point> points;
        for (auto &q : arena.objectives().ingress().at(site).at(order->value("lane", 0)))
            if (facing(hold, watch, q) && !nav.hit(hold, q, 1, 64, 64) &&
                std::find(points.begin(), points.end(), q) == points.end())
                points.push_back(q);
        if (std::find(points.begin(), points.end(), watch) == points.end())
            points.push_back(watch);
        double best = 0;
        focus = watch;
        int familiar = player.at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0),
            reading = skills.at("game_reading");
        for (auto &r : intel) {
            auto age = now - r.at("tick").get<Tick>();
            if (age < 0 || age >= 75)
                continue;
            auto last = actor_point(r);
            auto proj = expected(r, age, reading);
            double confidence =
                (1 - age / 75.) * ((r.at("source") == "Слух" || r.at("source") == "Граната") ? .5 : 1.);
            for (auto &q : points) {
                auto gap = distance(last, q);
                if (gap > 12 + proj + familiar / 4. ||
                    (std::abs(q[2] - last[2]) > 6 && nav.hit(last, q, 1, 48, 48)))
                    continue;
                double forward = 0;
                if (active(r, "direction")) {
                    auto d = r.at("direction").get<Point>();
                    forward =
                        sum3((q[0] - last[0]) * d[0], (q[1] - last[1]) * d[1], (q[2] - last[2]) * d[2]) /
                        std::max(1., gap);
                }
                auto strength = confidence * (1 + std::max(0., forward) * reading / 100) /
                                (1 + (forward > 0 ? std::abs(gap - proj) : gap));
                if (strength > best) {
                    best = strength;
                    focus = q;
                }
            }
        }
    }
    a["sectorReview"] = Json{{"token", token}, {"focus", focus}, {"next", now + 5}};
    return *order;
}
std::optional<Point> AgentTurn::flank(Json &order, const Json &home) {
    const auto &nav = arena.objectives().map();
    auto pos = actor_point(a), goal = order.at("hold").get<Point>();
    Tick timer = w.at("deadline").get<Tick>() - now;
    if (!order.contains("flank")) {
        order["flank"] = nullptr;
        bool ahead = active(home, "screen") && distance(pos, home.at("screen").at("hold").get<Point>()) <= 30;
        if ((!ahead && slot < 2) || timer < 125 ||
            skills.at("map_control").get<int>() + skills.at("decisions").get<int>() < 115 ||
            std::ranges::none_of(
                squad, [&](auto m) { return m != &a && distance(actor_point(*m), goal) < 65; }))
            return {};
        auto to = nav.locate(goal);
        if (!to)
            return {};
        auto direct = nav.path(a.at("navArea"), pos, *to, goal, {});
        if (!direct)
            return {};
        auto length = [](Point pos, const WalkPath &path, double value = 0.) {
            for (auto &[x, y, z, to] : path) {
                Point q{x, y, z};
                value += distance(pos, q);
                pos = q;
            }
            return value;
        };
        double limit =
            std::min(timer * 1.6 - 45, length(pos, *direct) + skills.at("timing").get<int>() * .65);
        std::string site = order.at("site");
        auto labels = arena.profile().at("guards").at(site);
        labels.push_back(arena.profile().at(site).at(1 - order.at("lane").get<int>()).back());
        std::set<AreaId> ids;
        for (auto &l : labels) {
            auto &v = arena.layout().places.at(l.get<std::string>());
            ids.insert(v.begin(), v.end());
        }
        std::vector<AreaId> choices(ids.begin(), ids.end());
        auto key = [&](auto i) {
            return std::pair{distance(pos, nav.center(i)) + distance(nav.center(i), goal), i};
        };
        std::sort(choices.begin(), choices.end(), [&](auto l, auto r) { return key(l) < key(r); });
        for (auto i : choices) {
            auto &q = nav.center(i);
            if (distance(pos, q) < 8 || distance(goal, q) < 12 ||
                std::ranges::any_of(*direct, [&](const Waypoint &n) {
                    return distance(Point{std::get<0>(n), std::get<1>(n), std::get<2>(n)}, q) < 14;
                }))
                continue;
            auto out = nav.path(a.at("navArea"), pos, i, q, {}), in = nav.path(i, q, *to, goal, {});
            if (out && in) {
                auto all = *out;
                all.insert(all.end(), in->begin(), in->end());
                if (length(pos, all) < limit) {
                    order["flank"] = q;
                    break;
                }
            }
        }
    }
    if (active(order, "flank") &&
        (distance(pos, order.at("flank").get<Point>()) < 4 || a.value("blockedTicks", 0) >= 5 || timer < 70))
        order["flank"] = nullptr;
    return active(order, "flank") ? std::optional<Point>{order.at("flank").get<Point>()} : std::nullopt;
}
} // namespace esport
