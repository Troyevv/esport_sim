#include "opening.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace esport {
namespace {
const auto infinity = std::numeric_limits<double>::infinity();
using Squad = std::vector<const Json *>;
Squad squad_for(const Json &w, const std::string &side) {
    Squad squad;
    for (const auto &a : w.at("agents"))
        if (a.at("team") == side)
            squad.push_back(&a);
    return squad;
}
const Json &player_for(const Json &w, const Json &a) {
    return w.at("domain").at("players").at(a.at("playerId").get<std::string>());
}
Point xyz(const Json &p) { return {p.at("x"), p.at("y"), p.at("z")}; }
std::string opposite(const std::string &site) { return site == "A" ? "B" : "A"; }
// CPython 3.12 sums floats with compensated summation.
struct Sum {
    double sum{}, error{};
    void add(double x) {
        double t = sum + x;
        error += std::abs(sum) >= std::abs(x) ? (sum - t) + x : (x - t) + sum;
        sum = t;
    }
    double value() const { return sum + error; }
};
} // namespace
OpeningMap::OpeningMap(std::shared_ptr<const Objectives> objectives, const std::string &profile,
                       const std::string &defense, ContestTable contest, Stations stations,
                       std::map<std::string, Point> sites, OrderData orders)
    : objectives_(std::move(objectives)), profile_(Json::parse(profile)), defense_(Json::parse(defense)),
      contest_(std::move(contest)), stations_(std::move(stations)), orders_(std::move(orders)),
      sites_(std::move(sites)) {
    if (!objectives_)
        throw std::invalid_argument("Отсутствуют данные карты");
    for (const std::string site : {"A", "B"})
        for (int lane : {0, 1}) {
            std::vector<std::vector<AreaId>> groups;
            for (const auto &label : profile_.at(site).at(lane))
                groups.push_back(orders_.places.at(label.get<std::string>()));
            groups.push_back(orders_.plants.at(site));
            approaches_.emplace(std::pair{site, lane}, objectives_->map().graph().routes_through(groups));
        }
}

Json OpeningMap::call(Json &w, Json &captain, const Json &buy, std::string site, std::string style,
                      const Json &coach) const {
    const auto &player = player_for(w, captain);
    const auto &skill = player.at("skills");
    const auto side = captain.at("team");
    const auto club = captain.at("teamId").get<std::string>();
    const int knowledge = player.at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0);
    int lane = (draw_rng(captain) >> 16) % 2;
    const auto history = w.value("siteHistory", Json::object()).value(club, Json::array());
    if (coach.is_null() && side == "T" && !history.empty()) {
        std::map<std::string, Sum> values;
        int age = 0;
        for (auto it = history.rbegin(); it != history.rend(); ++it) {
            ++age;
            if ((*it)[0].is_string())
                values[(*it)[0].get<std::string>()].add(((*it)[1] == true ? 1. : -1.) / age);
        }
        if (values[site].value() < values[opposite(site)].value() &&
            skill.at("calling").get<int>() + knowledge > int((draw_rng(captain) >> 16) % 200))
            site = opposite(site);
    }
    if (side == "T" && coach != "Ускориться" && coach != "Выход A" && coach != "Выход B") {
        if (buy == "Антиэко") {
            auto label = profile_.at("probe").at(site);
            auto has = [&](int j) {
                const auto &v = profile_.at(site).at(j);
                return std::find(v.begin(), v.end(), label) != v.end();
            };
            lane = has(0) && !has(1);
            style = "Контроль карты";
        } else if (style == "Быстро" && coach.is_null()) {
            auto squad = squad_for(w, "T");
            auto arrival = [&](int j) {
                std::vector<double> times;
                auto &[costs, defender] = contest_.at(site).at(j);
                for (auto a : squad) {
                    auto it = costs.find(a->at("navArea").get<AreaId>());
                    times.push_back(it == costs.end() ? infinity : it->second);
                }
                std::sort(times.begin(), times.end());
                return times.at(1);
            };
            if (buy == "Эко" || buy == "Частичная" || buy == "Форс" || buy == "Бонусная") {
                auto margin = [&](int j) { return arrival(j) - contest_.at(site).at(j).second; };
                lane = margin(1) < margin(0);
                style = "Групповой выход";
            }
            if (arrival(lane) > contest_.at(site).at(lane).second)
                style = "Контроль карты";
        } else if (knowledge + skill.at("map_control").get<int>() >= 115 && style == "Сбор")
            style = "Контроль карты";
    }
    return Json::array({site, style, lane});
}

Json defensive_read(const Json &w, const Json &captain) {
    auto h = w.value("defensiveHistory", Json::object())
                 .value(captain.at("teamId").get<std::string>(), Json::array());
    if (h.size() < 2 || h.back().is_null())
        return nullptr;
    return std::count(h.end() - std::min<std::size_t>(3, h.size()), h.end(), h.back()) >= 2 ? h.back()
                                                                                            : Json(nullptr);
}

Json OpeningMap::select_defense(const Json &w, Json &captain, const Json &plan, const Json &predicted,
                                const Json &explicit_site) const {
    auto squad = squad_for(w, "CT");
    const auto &p = player_for(w, captain);
    const auto &skills = p.at("skills");
    const auto &calls = defense_.at("plays"), zones = defense_.at("zones");
    const auto site = explicit_site.is_null() ? predicted : explicit_site;
    auto priority = [&](const Json &seats, const Json &value) {
        int n = 0;
        for (const auto &z : seats)
            n += zones.at(z.get<std::string>())[0] == value;
        return n;
    };
    int familiarity = p.at("mapKnowledge").value(w.at("mapId").get<std::string>().substr(3), 0);
    int quiet = 7 + ((plan.at("buy") == "Эко" || plan.at("buy") == "Частичная") ? 20 : 0) +
                (200 - skills.at("calling").get<int>() - familiarity) / 12;
    int total = quiet;
    std::vector<int> weights;
    for (const auto &seats : calls) {
        int paired = 0;
        Sum spawns;
        for (auto a : squad) {
            auto z = seats.at(a->at("slot").get<int>());
            paired = std::max(paired, int(std::count(seats.begin(), seats.end(), z)));
            const auto &options = stations_.at(zones.at(z.get<std::string>())[1].get<std::string>());
            double d = infinity;
            for (const auto &q : options)
                d = std::min(d, distance(xyz(*a), q));
            if (!std::isfinite(d))
                throw std::invalid_argument("Отсутствует сектор карты");
            spawns.add(d);
        }
        int weight =
            std::max(3, 18 + priority(seats, site) * (explicit_site.is_null() ? 5 : 12) +
                            paired * (skills.at("coordination").get<int>() / 25) - int(spawns.value() / 70));
        weights.push_back(weight);
        total += weight;
    }
    auto draw = draw_rng(captain);
    int roll = ((draw ^ (draw >> 16)) * 0x9E3779B1u) % total;
    if (roll < quiet) {
        auto preferred = site.is_null() ? plan.at("site") : site;
        auto best = std::max_element(calls.begin(), calls.end(), [&](const auto &a, const auto &b) {
            return priority(a, preferred) < priority(b, preferred);
        });
        return Json::array({"Закрытая защита", *best, true});
    }
    roll -= quiet;
    std::size_t i = 0;
    for (auto it = calls.begin(); it != calls.end(); ++it, ++i) {
        if (roll < weights[i])
            return Json::array({it.key(), it.value(), false});
        roll -= weights[i];
    }
    throw std::logic_error("Invalid defensive opening weights");
}

Json OpeningMap::attack_orders(const Json &w, const std::string &site, int lane,
                               const std::string &style) const {
    const auto &nav = objectives_->map();
    auto squad = squad_for(w, "T");
    std::stable_sort(squad.begin(), squad.end(),
                     [](auto a, auto b) { return a->at("slot") < b->at("slot"); });
    // Keep the carrier and entry together. Assign the opposite route to two
    // living players who can cover one another, even after a substitution.
    std::set<int> wing;
    if (collective_attack(w) && style != "Групповой выход") {
        auto candidates = squad;
        std::erase_if(candidates, [&](auto a) {
            return a->at("hp") == 0 || a->at("id") == w.at("bomb").at("carrier");
        });
        if (candidates.size() >= 3) {
            const auto &costs = contest_.at(site).at(1 - lane).first;
            auto fit = [&](const Json *a) {
                auto role = a->at("playingRole").get<std::string>();
                auto it = costs.find(a->at("navArea").get<AreaId>());
                double travel = it == costs.end() ? infinity : it->second / nav.unit();
                return std::tuple{role == "entry", role == "support", role != "lurker",
                                  travel, a->at("slot").get<int>()};
            };
            std::stable_sort(candidates.begin(), candidates.end(), [&](auto a, auto b) { return fit(a) < fit(b); });
            wing.insert(candidates[0]->at("slot").get<int>());
            wing.insert(candidates[1]->at("slot").get<int>());
        }
    }
    Json slots = Json::array();
    auto reachable = [&](const Point &start, const std::vector<Point> &options) -> std::optional<Point> {
        auto from = nav.locate(start);
        if (from)
            for (const auto &q : options) {
                auto goal = nav.locate(q);
                if (goal && nav.path(*from, start, *goal, q, {}))
                    return q;
            }
        return {};
    };
    for (const auto *a : squad) {
        const int i = a->at("slot");
        int variant = (i % 2 == 0 || style == "Групповой выход" || a->at("playingRole") == "entry" ||
                       a->at("playingRole") == "support")
                          ? lane
                          : 1 - lane;
        auto start = a->at("navArea").get<AreaId>();
        if (collective_attack(w))
            variant = wing.contains(i) ? 1 - lane : lane;
        auto selected = approaches_.at({site, variant}).route(start);
        if (!selected) {
            selected = approaches_.at({site, 1 - variant}).route(start);
            if (selected && collective_attack(w))
                variant = 1 - variant;
        }
        Point plant = sites_.at(site);
        auto pos = xyz(*a);
        std::vector<Point> via;
        if (selected) {
            const auto &markers = selected->second;
            plant = nav.center(markers.back());
            for (std::size_t j = 0; j + 1 < markers.size(); ++j) {
                const auto marker = markers[j];
                std::vector<Point> options{nav.center(marker)};
                for (auto id : orders_.nearby.at(marker))
                    if (nav.center(id) != options.front())
                        options.push_back(nav.center(id));
                if (auto next = reachable(pos, options)) {
                    via.push_back(*next);
                    pos = *next;
                }
            }
        }
        std::vector<Point> covers;
        for (auto &[id, p] : orders_.holds.at(site))
            if (distance(p, plant) < 55 && nav.graph().route(start, id, {}, {}))
                covers.push_back(p);
        Point hold = covers.empty() ? plant : covers.at((i + lane * 3) % covers.size());
        std::vector<Point> plants;
        for (auto id : orders_.plants.at(site))
            plants.push_back(nav.center(id));
        std::stable_sort(plants.begin(), plants.end(), [&](const auto &a, const auto &b) {
            return distance(a, plant) < distance(b, plant);
        });
        auto landing = reachable(pos, plants);
        while (!landing && !via.empty()) {
            via.pop_back();
            pos = via.empty() ? xyz(*a) : via.back();
            landing = reachable(pos, plants);
        }
        if (landing)
            plant = *landing;
        std::vector<Point> options{hold};
        for (const auto &[id, p] : orders_.holds.at(site))
            options.push_back(p);
        options.push_back(plant);
        hold = reachable(pos, options).value_or(pos);
        auto label = profile_.at(site).at(variant).back().get<std::string>();
        auto &views = orders_.places.at(label);
        auto watch = std::min_element(views.begin(), views.end(), [&](auto a, auto b) {
            return distance(nav.center(a), hold) < distance(nav.center(b), hold);
        });
        if (watch == views.end())
            throw std::invalid_argument("Отсутствуют позиции наблюдения");
        slots.push_back(Json{{"role", orders_.roles.at(i)},
                             {"approach", via.empty() ? hold : via.front()},
                             {"via", via},
                             {"stage", via.empty() ? plant : via.back()},
                             {"hold", hold},
                             {"plant", plant},
                             {"site", site},
                             {"lane", variant},
                             {"watch", nav.center(*watch)}});
    }
    return Json{{"version", 1}, {"map", w.at("mapId")}, {"geometry", w.at("map_version")}, {"slots", slots}};
}

Json OpeningMap::default_probe(const Json &w, const Json &plan, const Json &cfg) const {
    const auto squad = squad_for(w, "T");
    auto eligible = squad;
    std::erase_if(eligible, [&](const auto *a) { return a->at("id") == w.at("bomb").at("carrier"); });
    auto pick = [&](auto rank) {
        auto it = std::min_element(eligible.begin(), eligible.end(),
                                   [&](const auto *a, const auto *b) { return rank(*a) < rank(*b); });
        if (it == eligible.end())
            throw std::invalid_argument("Неполный состав");
        auto p = *it;
        eligible.erase(it);
        return p;
    };
    const auto map = w.at("mapId").get<std::string>().substr(3);
    auto scout = pick([&](const Json &a) {
        const auto &p = player_for(w, a);
        int fit = p.at("skills").at("lurking").get<int>() + p.at("roleMastery").value("lurker", 0) +
                  p.at("mapKnowledge").value(map, 0);
        return std::tuple{a.at("playingRole") != "lurker", -fit, a.at("slot").get<int>()};
    });
    auto mid = pick(
        [](const Json &a) { return std::pair{a.at("playingRole") != "awper", a.at("slot").get<int>()}; });
    auto partner = pick(
        [](const Json &a) { return std::pair{a.at("playingRole") == "entry", a.at("slot").get<int>()}; });
    Json stations = Json::object();
    const auto site = plan.at("site").get<std::string>();
    const auto &nav = objectives_->map();
    for (auto a : squad) {
        auto sector = a == scout || a == partner ? opposite(site) : site;
        std::string label = a == mid ? profile_.at("middle") : profile_.at("probe").at(sector);
        Point origin = xyz(*a);
        std::vector<Point> occupied;
        for (const auto &station : stations)
            if (station.at("label") == label)
                occupied.push_back(station.at("point").get<Point>());
        auto options = stations_.at(label);
        auto cost = [&](const Point &q) {
            return std::pair{
                std::ranges::any_of(occupied, [&](const Point &p) { return distance(q, p) < 8; }),
                distance(origin, q) + (occupied.empty() ? 0. : std::abs(distance(q, occupied.front()) - 16))};
        };
        std::stable_sort(options.begin(), options.end(),
                         [&](const Point &a, const Point &b) { return cost(a) < cost(b); });
        auto it = std::find_if(options.begin(), options.end(), [&](const Point &q) {
            auto dest = nav.locate(q);
            return dest && nav.path(a->at("navArea"), origin, *dest, q, {}).has_value();
        });
        if (it == options.end())
            return nullptr;
        auto watch = sites_.at(sector);
        double nearest = infinity;
        auto consider = [&](const Point &q) {
            double d = distance(*it, q);
            if (d > 6 && d < nearest && !nav.hit(*it, q, 1, 64, 64)) {
                watch = q;
                nearest = d;
            }
        };
        consider(sites_.at(sector));
        for (const auto &q : objectives_->ingress().at(sector).at(plan.at("lane").get<int>()))
            consider(q);
        stations[a->at("id").get<std::string>()] =
            Json{{"label", label}, {"sector", sector}, {"point", *it}, {"watch", watch}};
    }
    return Json{{"scout", scout->at("id")},
                {"stations", stations},
                {"reports", Json::object()},
                {"until", plus_ticks(w.at("tick"), cfg.at("rules").at("live").get<int>() -
                                                       cfg.at("rules").at("plant").get<int>())}};
}
} // namespace esport
