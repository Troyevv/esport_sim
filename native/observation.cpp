#include "observation.hpp"
#include <algorithm>
#include <bit>
#include <charconv>
#include <cmath>
#include <numbers>

namespace esport {
namespace {
std::optional<Json> crossing_report(const Objectives &sites, const Json &a, const Json &roster,
                                    const Json &plan, const std::vector<Hazard> &smoke, Tick now);
Point xyz(const Json &obj) { return {obj.at("x"), obj.at("y"), obj.at("z")}; }
bool viewing(const Json &a, const Point &p) {
    const auto pos = xyz(a);
    const double x = p[0] - pos[0], y = p[1] - pos[1], h = a.at("heading");
    const double d = x * std::cos(h) + y * std::sin(h);
    return d >= 0 && 4 * d * d >= x * x + y * y;
}
bool has(const Json &array, const Json &id) {
    return std::find(array.begin(), array.end(), id) != array.end();
}
void report(Json &w, const Json &a, const char *key, const Json &value) {
    const auto &s = w.at("domain").at("players").at(a.at("playerId").get<std::string>()).at("skills");
    const int delay = 1 + (100 - s.at("communication").get<int>()) / 12;
    w.at("messages")
        .push_back(Json{{"team", a.at("team")},
                        {"sender", a.at("id")},
                        {key, value},
                        {"due", plus_ticks(w.at("tick"), delay)}});
}
void sector(Json &w, Json &a, const Json &call) {
    a["sectorCalls"][a.at("id").get<std::string>()] = call;
    report(w, a, "crossing", call);
}
void motion(Json &observer, Json &sight, const Json &prior) {
    if (!observer.contains("motionHistory"))
        observer["motionHistory"] = Json::object();
    auto &memory = observer.at("motionHistory");
    const bool prior_direction = prior.contains("direction") && !prior.at("direction").empty();
    if (prior_direction && (prior.at("source") == "Зрение" || prior.at("source") == "Радио")) {
        const auto elapsed = sight.at("tick").get<Tick>() - prior.at("tick").get<Tick>();
        const double speed = prior.value("speed", 0.);
        if (elapsed > 1 && elapsed <= 24 && speed > 0) {
            auto p = xyz(prior), q = xyz(sight);
            const auto dir = prior.at("direction").get<Point>();
            double traveled = sum3((q[0] - p[0]) * dir[0], (q[1] - p[1]) * dir[1], (q[2] - p[2]) * dir[2]);
            std::string bucket = std::to_string(std::bit_width(static_cast<unsigned>(elapsed)) - 1);
            Json old = memory.value(bucket, Json::array({0, 0}));
            double ratio = traveled / (elapsed * speed);
            Json total;
            if (old.at(0).is_number_integer() && (ratio <= 0 || ratio >= 1))
                total = old.at(0).get<int>() + int(ratio >= 1);
            else
                total = old.at(0).get<double>() + std::clamp(ratio, 0., 1.);
            memory[bucket] = Json::array({total, old.at(1).get<int>() + 1});
        }
    }
    if (sight.contains("motionRun") && !memory.empty())
        sight["motionHistory"] = memory;
}
Json sighting(Json &a, const Json &b, const Json &prior, const Json &previous, int nearby, Tick now) {
    Json sight = {{"id", b.at("id")}, {"x", b.at("x")}, {"y", b.at("y")},
                  {"z", b.at("z")},   {"tick", now},    {"source", "Зрение"}};
    const bool continuous = !prior.empty() && has(previous, b.at("id")) && prior.at("tick") == now - 1;
    const double speed = continuous ? distance(xyz(prior), xyz(b)) : 0;
    if (continuous)
        sight["speed"] = speed;
    sight["weapon"] = b.at("weapon");
    int direction = int(std::nearbyint(b.at("heading").get<double>() / (std::numbers::pi / 4))) % 8;
    sight["bodySector"] = (direction + 8) % 8;
    sight["groupSize"] = nearby;
    if (continuous && speed > .05) {
        Point dir;
        const auto p = xyz(prior), q = xyz(b);
        for (int j = 0; j < 3; ++j)
            dir[j] = round_decimal((q[j] - p[j]) / speed, 3);
        sight["direction"] = dir;
        bool aligned = false;
        if (prior.contains("direction") && !prior.at("direction").empty()) {
            auto old = prior.at("direction").get<Point>();
            aligned =
                sum3(old[0] * dir[0], old[1] * dir[1], old[2] * dir[2]) >= std::cos(std::numbers::pi / 8);
        }
        sight["motionRun"] = 1 + (aligned ? prior.value("motionRun", 1) : 0);
    }
    motion(a, sight, prior);
    return sight;
}
std::string evidence_sector(const Json &x) {
    double sector = std::floor(x.get<double>() / 40) + 1;
    if (x.is_number_integer())
        return std::to_string(static_cast<std::int64_t>(sector));
    char text[64];
    const auto end = std::to_chars(text, text + sizeof(text), sector, std::chars_format::fixed, 1);
    if (end.ec != std::errc{})
        throw std::invalid_argument("Invalid evidence sector");
    return {text, end.ptr};
}
} // namespace

void observe_contacts(Json &w, const MapSensors &sensors, const Objectives &sites) {
    Tick now = w.at("tick");
    auto &roster = w.at("agents");
    std::vector<std::size_t> alive;
    std::vector<Observer> inputs;
    for (std::size_t i = 0; i < roster.size(); ++i) {
        const auto &a = roster.at(i);
        if (a.at("hp") == 0)
            continue;
        alive.push_back(i);
        inputs.push_back({xyz(a), a.at("heading"), a.at("team") == "T", a.at("blind") > now});
    }
    std::vector<Hazard> smoke;
    for (const auto &f : w.at("effects"))
        if (f.at("kind") == "Дым" && f.at("land") <= now && f.at("end") > now)
            smoke.emplace_back(xyz(f), f.at("radius"));
    const auto seen = sensors.observe(inputs, smoke);
    for (std::size_t i = 0; i < alive.size(); ++i) {
        auto &a = roster.at(alive[i]);
        Json previous = std::move(a.at("visible"));
        a["visible"] = Json::array();
        auto &knowledge = a.at("knowledge");
        for (auto it = knowledge.begin(); it != knowledge.end();) {
            if (now - it.value().at("tick").get<Tick>() >= 75)
                it = knowledge.erase(it);
            else
                ++it;
        }
        if (a.at("blind") > now)
            continue;
        for (auto j : seen[i]) {
            const auto &b = roster.at(alive[j]);
            const std::string id = b.at("id");
            Json prior = a.at("knowledge").value(id, Json::object());
            int nearby = 0;
            for (auto k : seen[i]) {
                const auto &p = inputs[k].position;
                if (distance(p, inputs[j].position) <= 28 && std::abs(p[2] - inputs[j].position[2]) < 8)
                    ++nearby;
            }
            auto sight = sighting(a, b, prior, previous, nearby, now);
            if (!w.at("action").is_null() && w.at("action").at("player") == id)
                sight["interaction"] = w.at("action").at("kind");
            if (b.at("team") == "T" && w.at("bomb").at("carrier") == id)
                sight["carryingC4"] = true;
            a.at("visible").push_back(id);
            a.at("knowledge")[id] = sight;
            bool changed = false;
            if (!prior.empty()) {
                for (const auto key : {"weapon", "carryingC4", "interaction", "groupSize"})
                    if (prior.value(key, Json(nullptr)) != sight.value(key, Json(nullptr)))
                        changed = true;
                if (sight.contains("direction") && !prior.contains("direction"))
                    changed = true;
            }
            bool acquired = !has(previous, id);
            if (acquired || now % 10 == 0 || changed)
                report(w, a, "sight", sight);
            if (acquired) {
                auto &e =
                    emit(w, "contact",
                         a.at("name").get<std::string>() + " заметил " + b.at("name").get<std::string>(),
                         a.at("team"));
                e.update(Json{{"player", a.at("id")}, {"target", id}, {"x", b.at("x")}, {"y", b.at("y")}});
                a["evidence"] =
                    Json{{"id", e.at("id")},
                         {"round", w.at("round")},
                         {"text", "В раунде " + std::to_string(w.at("round").get<int>()) + " я видел " +
                                      b.at("name").get<std::string>() + " в секторе " +
                                      evidence_sector(b.at("x")) + ". Стоит перепроверить подход."}};
            }
        }
        if (a.at("team") == "CT" && w.at("phase") == "live") {
            Json latest = nullptr;
            for (const auto &pid : previous) {
                auto id = pid.get<std::string>();
                if (has(a.at("visible"), pid) || !a.at("knowledge").contains(id))
                    continue;
                const auto &sight = a.at("knowledge").at(id);
                if (latest.is_null() || latest.at("tick") < sight.at("tick"))
                    latest = sight;
            }
            if (!latest.is_null()) {
                if (auto site = sites.reported_site(xyz(latest)))
                    sector(w, a,
                           Json{{"state", "lost"},
                                {"point", Json::array({latest.at("x"), latest.at("y"), latest.at("z")})},
                                {"site", *site},
                                {"lane", w.at("plans").at("CT").at("lane")},
                                {"tick", now}});
            }
        }
    }
    if (w.at("phase") == "live" && now % 5 == 0 && w.at("plans").contains("CT")) {
        const auto &plan = w.at("plans").at("CT");
        if (plan.contains("orders") && plan.at("orders").contains("slots") &&
            !plan.at("orders").at("slots").empty()) {
            for (auto i : alive) {
                auto &a = roster.at(i);
                if (a.at("team") == "CT" && a.at("slot") == (now / 5) % 5) {
                    if (auto call = crossing_report(sites, a, roster, plan, smoke, now))
                        sector(w, a, *call);
                    break;
                }
            }
        }
    }
}
namespace {
std::optional<Json> crossing_report(const Objectives &sites, const Json &a, const Json &roster,
                                    const Json &plan, const std::vector<Hazard> &smoke, Tick now) {
    const auto &slots = plan.at("orders").at("slots");
    const auto id = a.at("id").get<std::string>();
    const int slot = a.at("slot");
    const Json *relief = nullptr;
    for (const auto key : {"backup", "secondBackup"})
        if (plan.contains(key) && !plan.at(key).empty() && plan.at(key).at("id") == id) {
            relief = &plan.at(key);
            break;
        }
    if (!relief && plan.contains("commitments") && plan.at("commitments").contains(id))
        relief = &plan.at("commitments").at(id);
    const Json *order = relief ? relief : &slots.at(slot);
    if (!relief) {
        if ((slot == 2 || slot == 3) && order->at("site") == slots.at(slot - 2).at("site") &&
            std::ranges::none_of(roster, [&](const auto &p) {
                return p.at("team") == "CT" && p.at("hp") != 0 && p.at("slot") == slot - 2;
            }))
            order = &slots.at(slot - 2);
        else if (order->contains("screen") && !order->at("screen").empty() && !a.value("leftScreen", false))
            order = &order->at("screen");
    }
    if (a.at("blind") > now)
        return std::nullopt;
    const auto pos = xyz(a);
    auto report = [&](const Point &p, const Json &site, double radius, bool opening) -> Json {
        bool blocked = std::ranges::any_of(
            smoke, [&](const auto &f) { return near_segment(pos, p, f.first, f.second); });
        bool contact = std::ranges::any_of(a.at("visible"), [&](const auto &target) {
            return distance(xyz(a.at("knowledge").at(target.template get<std::string>())), p) < radius;
        });
        std::string state = opening && blocked ? "obscured"
                            : contact          ? "contact"
                            : blocked          ? "obscured"
                                               : "watching";
        return Json{
            {"site", site}, {"lane", order->value("lane", 0)}, {"point", p}, {"tick", now}, {"state", state}};
    };
    if (!relief && plan.contains("opening") && plan.at("opening").contains("jobs") &&
        plan.at("opening").at("jobs").contains(id)) {
        const auto &job = plan.at("opening").at("jobs").at(id);
        if (job.contains("peek") && distance(pos, job.at("peek").get<Point>()) < 7) {
            const auto p = job.at("watch").get<Point>();
            if (viewing(a, p) && !sites.map().hit(pos, p, 1, 64, 64))
                return report(p, job.at("site"), 28, true);
        }
    }
    if (a.at("reloadAt") != 0 || a.at("ammo") == 0 || distance(pos, order->at("hold").get<Point>()) > 12)
        return std::nullopt;
    const auto site = order->at("site").get<std::string>();
    auto points = sites.ingress().at(site).at(order->value("lane", 0));
    auto watch = order->at("watch").get<Point>();
    std::stable_sort(points.begin(), points.end(),
                     [&](const Point &p, const Point &q) { return distance(p, watch) < distance(q, watch); });
    for (const auto &p : points)
        if (viewing(a, p) && !sites.map().hit(pos, p, 1, 64, 64))
            return report(p, site, 18, false);
    return std::nullopt;
}
} // namespace
} // namespace esport
