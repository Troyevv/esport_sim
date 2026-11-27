#include "agent_turn.hpp"
#include "grid_round.hpp"
#include <algorithm>
#include <cmath>
#include <numbers>
namespace esport {
Json AgentTurn::grid_exit() {
    auto site = device.empty() ? Json(nullptr) : device.at("site");
    if (site.empty())
        site = a.at("heardSite");
    if (site.empty())
        site = plan.at("reinforce");
    if (site.empty())
        return nullptr;
    auto target = !device.empty() && device.contains("x")
                      ? xy(device)
                      : grid->data.at("positions").at(site.get<std::string>())[0].get<XY>();
    auto cell = grid->cell(xy(a));
    auto [length, goal] = grid->escape(cell, target, cfg.at("blastRadius"));
    double speed = 2 * move_speed(player), escape = length / grid->unit * std::ceil(grid->unit / speed) + 5;
    auto remaining = w.at("deadline").get<Tick>() - now;
    int reports = 0;
    for (auto &p : a.at("knowledge"))
        reports +=
            p.at("source") != "Слух" && now - p.at("tick").get<Tick>() <= 30 && gap2(xy(p), target) < 75;
    int value = equipment_value(a, cfg),
        reserve =
            std::min(24, value / 450 + (100 - a.at("hp").get<int>()) / 10 + (a.at("cash") < 1800 ? 6 : 0));
    if (side == "CT") {
        if (!action.empty())
            return nullptr;
        auto path = grid->route(cell, grid->cell(target));
        double approach = std::max(0., (path.size() * grid->unit - 8) / speed);
        int use = cfg.at("rules").at(a.at("kit") == true ? "kitDefuse" : "defuse");
        if (!device.empty() && gap(device) <= 8 && remaining > use)
            return nullptr;
        int opposition = std::max(0, reports - int(squad.size()) + 1);
        double margin = std::min(50., approach * speed / 2) * (100 - skills.at("retakes").get<int>()) / 100 +
                        (50 - skills.at("risk").get<int>()) * std::min(1., value / 3000.) / 2;
        if (remaining > approach + use + std::max(0., opposition * (12 + reserve) + margin))
            return nullptr;
    } else if (remaining > escape + (reports ? 0 : reserve))
        return nullptr;
    return grid->point(grid->cell(goal));
}
Json AgentTurn::grid_intent() {
    auto intent = [](std::string kind, Json arg = nullptr) { return Json::array({kind, std::move(arg)}); };
    auto coordinates = [](const Json &a) { return Json::array({a.at("x"), a.at("y")}); };
    auto walk = [&](const Json &goal, double pace) {
        return grid->walk(a, goal, pace * move_speed(player), grid_fire, false);
    };
    bool planted = w.at("phase") == "planted";
    std::string site = plan.at("site");
    auto &positions = grid->data.at("positions");
    bool rescuer = false;
    if (side == "T" && !device.empty() && device.at("carrier").is_null() && device.at("site").is_null()) {
        auto rank = [&](const Json *p) {
            return std::pair{gap2(xy(*p), xy(device)), p->at("id").get<std::string>()};
        };
        rescuer = *std::min_element(squad.begin(), squad.end(),
                                    [&](auto x, auto y) { return rank(x) < rank(y); }) == &a;
    }
    bool reinforce = side == "CT" && (planted || (!plan.at("reinforce").empty() && (slot == 1 || slot == 4)));
    if (!rescuer && !reinforce && squad.size() < 5 && a.at("playingRole") == "support" && !planted &&
        (device.empty() || device.at("carrier") != a.at("id"))) {
        auto partner = squad.front();
        for (auto mate : squad)
            if (mate->at("id") == plan.at("captain"))
                partner = mate;
        if (gap(*partner) > 75 - skills.at("support").get<int>() * .45 - chemistry(w, a, *partner) * .15) {
            a["status"] = "К капитану после потери союзника";
            return intent(walk(coordinates(*partner), 2) ? "move" : "hold");
        }
    }
    if (plan.contains("board") && !planted && plan.at("rotated") == false && !rescuer && !reinforce) {
        auto result = board_step(w, a, cfg, arena.objectives(), device, fire);
        if (!result.is_null())
            return result;
    }
    Json goal;
    auto &order = plan.at("orders").at("slots").at(slot);
    if (planted) {
        if (side == "CT") {
            if (!a.at("heardSite").empty())
                site = a.at("heardSite");
            else if (!plan.at("reinforce").empty())
                site = plan.at("reinforce");
            else if (slot % 2 == 0)
                site = site == "A" ? "B" : "A";
            bool teammate = !action.empty() && action.at("player") != a.at("id");
            if (!device.empty() && gap(device) <= 8 && !teammate)
                return intent("defuse");
            goal = !device.empty() && !teammate ? coordinates(device)
                                                : positions.at(site)[!device.empty() && teammate ? slot : 0];
            a["status"] = "Идёт на ретейк";
        } else {
            site = device.at("site");
            goal = positions.at(site)[slot];
            a["status"] = "Прикрывает C4";
        }
    } else if (side == "T") {
        bool separated = std::ranges::any_of(squad, [&](auto m) { return gap(*m) > 50; });
        bool staging = plan.at("style") == "Сбор" &&
                       now - plan.at("start").get<Tick>() <
                           65 + (100 - skills.at("timing").get<int>()) / 3 +
                               (separated ? skills.at("synchronization").get<int>() / 3 : 0);
        bool approach = a.at("approached") != site;
        if (approach && gap2(xy(a), order.at("approach").get<XY>()) < 6) {
            a["approached"] = site;
            approach = false;
        }
        goal = order.at(approach ? "approach" : staging ? "stage" : "hold");
        if (approach && a.at("playingRole") == "lurker" &&
            skills.at("lurking").get<int>() + player.at("mapKnowledge").value("depo", 0) >= 145) {
            goal = plan.at("orders").at("slots")[3].at("approach");
            if (gap2(xy(a), goal) < 6)
                a["approached"] = site;
        }
        a["status"] = staging ? "Собирается с командой" : "Выход на " + site;
        if (rescuer) {
            goal = coordinates(device);
            a["status"] = "Подбирает C4";
        } else if (!device.empty() && device.at("carrier") == a.at("id")) {
            if (!staging && !approach)
                goal = positions.at(site)[0];
            if (auto zone = grid->zone(xy(a)))
                return intent("plant", *zone);
        }
    } else {
        site = slot == 0 || slot == 2 ? "A" : "B";
        if (slot == 4 || (slot == 1 && !plan.at("reinforce").empty()))
            site = (plan.at("reinforce").empty() ? plan.at("site") : plan.at("reinforce")).get<std::string>();
        goal = positions.at(site)[slot];
        a["status"] = "Занимает " + site;
    }
    const Json *memory = nullptr;
    for (auto &m : a.at("knowledge"))
        if (!memory || memory->at("tick") < m.at("tick"))
            memory = &m;
    if (memory &&
        now - memory->at("tick").get<Tick>() < (memory->at("source") == "Слух"
                                                    ? 8 + (100 - skills.at("patience").get<int>()) / 3
                                                    : 12 + skills.at("aggression").get<int>() / 2) &&
        a.at("status") != "Сохраняет оружие" && a.at("status") != "Подбирает C4" &&
        (side != "CT" || gap2(goal, xy(*memory)) <= 145 - skills.at("discipline").get<int>()) &&
        (side == "CT" || (!device.empty() && a.at("id") != device.at("carrier")))) {
        goal = coordinates(*memory);
        a["status"] = "Проверяет сообщение о контакте";
    }
    if (walk(goal, planted || plan.at("style") == "Быстро" ? 2 : 1))
        return intent("move");
    auto status = a.at("status").get<std::string>();
    if (status.starts_with("Занимает") || status.starts_with("Выход"))
        a["status"] = "Контролирует " + site;
    constexpr auto pi = std::numbers::pi;
    double base = side == "CT" ? pi : 0.;
    auto p = xy(a);
    if (side == "CT" || planted) {
        bool ct = side == "CT";
        auto q = (ct ? order.at("approach") : positions.at(site)[0]).get<XY>();
        auto h = ct ? std::atan2(q[1] - p[1], q[0] - p[0]) : std::atan2(p[1] - q[1], p[0] - q[0]);
        auto d = std::fmod(h - base + pi, 2 * pi);
        if (d < 0)
            d += 2 * pi;
        base += (d - pi) * skills.at(ct ? "positioning" : "postplant").get<int>() / 100;
    }
    a["heading"] = base + 1.6 * std::sin((now + slot * 12) / (24 - skills.at("map_control").get<int>() / 8.));
    return intent("hold");
}
} // namespace esport
