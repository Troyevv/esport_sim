#include "grenades.hpp"
#include "radio.hpp"
#include "grid_round.hpp"
#include "economy.hpp"
#include <algorithm>
#include <cmath>
namespace esport {
namespace {
bool has(const Json &xs, const Json &v) { return std::find(xs.begin(), xs.end(), v) != xs.end(); }
} // namespace
std::string grid_buy(const Json &w, const Json &cfg, const std::string &side, const Json &call) {
    if (call == "Экономить")
        return "Эко";
    if (w.at("round") == 1 || w.at("round") == cfg.at("rules").at("half").get<int>() + 1)
        return "Пистолетная";
    int cash = 0, count = 0;
    for (auto &a : w.at("agents"))
        if (a.at("team") == side) {
            cash += a.at("cash").get<int>();
            ++count;
        }
    return cash >= 3600 * count ? "Полная" : cash >= 1900 * count ? "Форс" : "Эко";
}
void grid_purchase(Json &w, const Json &cfg, const std::string &side, const std::string &buy, Json &captain) {
    const bool armed = buy == "Полная" || buy == "Форс";
    std::string rifle = side == "T" ? "AK-47" : "M4A1-S", smg = side == "T" ? "MAC-10" : "MP9";
    Squad squad;
    for (auto &a : w.at("agents"))
        if (a.at("team") == side)
            squad.push_back(&a);
    for (auto mate : squad) {
        auto &a = *mate;
        if (!armed || !has(cfg.at("sidearms"), a.at("weapon")))
            continue;
        auto &s = player_profile(w, a).at("skills");
        auto best = rifle;
        if (a.at("playingRole") == "awper" && a.at("cash") >= 5400)
            best = "AWP";
        else if (buy == "Форс" && std::max(s.at("shotguns"), s.at("machine_guns")) > s.at("rifles"))
            best = s.at("shotguns") > s.at("machine_guns") ? "Nova" : "Negev";
        if (!purchase_item(w, cfg, a, best))
            purchase_item(w, cfg, a, smg);
    }
    for (auto mate : squad) {
        auto &a = *mate;
        int slot = a.at("slot");
        if (buy == "Эко")
            continue;
        if (has(cfg.at("sidearms"), a.at("weapon"))) {
            auto donor = *std::max_element(squad.begin(), squad.end(),
                                           [](auto x, auto y) { return x->at("cash") < y->at("cash"); });
            if (!has(cfg.at("sidearms"), donor->at("weapon")) &&
                donor->at("cash") >= cfg.at("weapons").at(rifle).at("price").get<int>() + 650)
                purchase_item(w, cfg, *donor, rifle, &a);
        }
        if (buy == "Форс" && (a.at("weapon") == "USP" || a.at("weapon") == "Glock"))
            purchase_item(w, cfg, a, "Desert Eagle");
        if (a.at("armor") < 45 && (buy != "Пистолетная" || slot < 3))
            purchase_item(w, cfg, a, "Броня");
        if (armed && a.at("armor") != 0 && a.at("helmet") == false)
            purchase_item(w, cfg, a, "Шлем");
        if (side == "CT" && a.at("kit") == false && slot % 2 == 0)
            purchase_item(w, cfg, a, "Набор");
        const std::array<std::string, 5> order{"Дым", "Свет", "HE", "Огонь", "Ложная"};
        for (int i = 0; i < 5 && a.at("utility").size() < 2; i++) {
            auto &item = order[(slot + w.at("round").get<int>() + i) % 5];
            if (!has(a.at("utility"), item))
                purchase_item(w, cfg, a, item);
        }
    }
    if (buy == "Эко") {
        auto &e =
            emit(w, "budget", captain.at("name").get<std::string>() + " предлагает сохранить деньги", side);
        e["player"] = captain.at("id");
        captain["evidence"] = Json{{"id", e.at("id")},
                                   {"round", w.at("round")},
                                   {"text", "Мы играли эко. Предлагаю согласовать следующую закупку."}};
    }
}
void grid_observe(Json &w, const GridMap &grid) {
    const Tick now = w.at("tick");
    for (auto &a : w.at("agents")) {
        if (a.at("hp") == 0)
            continue;
        auto previous = std::move(a.at("visible"));
        a["visible"] = Json::array();
        // ordered_json invalidates sibling references when a new actor field is inserted.
        if (peer_radio(w) && !a.contains("sentContacts"))
            a["sentContacts"] = Json::object();
        auto &intel = a.at("knowledge");
        for (auto it = intel.begin(); it != intel.end();)
            if (now - it->at("tick").get<Tick>() >= 75)
                it = intel.erase(it);
            else
                ++it;
        if (a.at("blind") > now)
            continue;
        for (auto &b : w.at("agents")) {
            if (b.at("hp") == 0 || b.at("team") == a.at("team") || !grid.sees(a, b) ||
                !recognizes(a, actor_point(b), now))
                continue;
            if (std::ranges::any_of(w.at("effects"), [&](auto &f) {
                    return f.at("kind") == "Дым" && f.at("land") <= now && now < f.at("end") &&
                           crosses_volume(f, actor_point(a), actor_point(b));
                }))
                continue;
            auto id = b.at("id").get<std::string>();
            bool seen = has(previous, id);
            Json sight = {
                {"id", id}, {"x", b.at("x")}, {"y", b.at("y")}, {"tick", now}, {"source", "Зрение"}};
            if (seen && intel.contains(id) && intel.at(id).at("tick") == now - 1)
                sight["speed"] = gap2(xy(intel.at(id)), xy(b));
            a.at("visible").push_back(id);
            intel[id] = sight;
            if (!seen || now % 10 == 0)
                report_contact(w, a, sight);
            if (!seen) {
                std::string name = b.at("name");
                auto &e =
                    emit(w, "contact", a.at("name").get<std::string>() + " заметил " + name, a.at("team"));
                e.update(Json{{"player", a.at("id")}, {"target", id}, {"x", b.at("x")}, {"y", b.at("y")}});
                Json sector = std::floor(b.at("x").get<double>() / 40) + 1;
                if (b.at("x").is_number_integer())
                    sector = int(sector.get<double>());
                a["evidence"] =
                    Json{{"id", e.at("id")},
                         {"round", w.at("round")},
                         {"text", "В раунде " + w.at("round").dump() + " я видел " + name + " в секторе " +
                                      sector.dump() + ". Стоит перепроверить подход."}};
            }
        }
    }
}
void grid_review(Json &w, const Squad &squad, const GridMap &grid) {
    auto rank = [](const Json &a) {
        return std::pair{!a.at("appointed").get<bool>(), a.at("slot").get<int>()};
    };
    auto &leader =
        **std::min_element(squad.begin(), squad.end(), [&](auto a, auto b) { return rank(*a) < rank(*b); });
    auto side = leader.at("team").get<std::string>();
    auto &plan = w.at("plans").at(side);
    const Tick now = w.at("tick");
    auto &skills = player_profile(w, leader).at("skills");
    if (plan.at("captain") != leader.at("id")) {
        plan["captain"] = leader.at("id");
        plan["review"] = now + (100 - skills.at("leadership").get<int>()) / 4;
        emit(w, "captain", leader.at("name").get<std::string>() + " принимает колл", side)["player"] =
            leader.at("id");
    }
    if (now < plan.at("review"))
        return;
    plan["review"] = now + 18 + (100 - skills.at("calling").get<int>()) / 2;
    std::map<std::string, int> counts{{"A", 0}, {"B", 0}};
    Json contacts = Json::array();
    for (auto &p : leader.at("knowledge")) {
        if (p.at("source") == "Слух" || p.at("source") == "Граната" ||
            now - p.at("tick").get<Tick>() > 74 - skills.at("game_reading").get<int>() / 2)
            continue;
        contacts.push_back(p.at("id"));
        for (auto &[site, n] : counts)
            n += gap2(grid.data.at("positions").at(site)[0].get<XY>(), xy(p)) < 80;
    }
    std::string site = plan.at("site");
    if (side == "T" && counts.at(site) >= 3 &&
        now - plan.at("start").get<Tick>() >= (100 - skills.at("adaptability").get<int>()) / 2 &&
        plan.at("rotated") == false && w.at("deadline").get<Tick>() - now > 250 && w.at("phase") == "live") {
        site = site == "A" ? "B" : "A";
        plan["site"] = site;
        plan["rotated"] = true;
        plan["orders"] = grid.data.at("orders").at(side).at(site);
        emit(w, "rotate",
             leader.at("name").get<std::string>() + " меняет направление после трёх контактов · " + site,
             side)
            .update(Json{{"player", leader.at("id")}, {"contacts", contacts}});
    }
    if (side == "CT") {
        if (counts["A"] != counts["B"] && std::max(counts["A"], counts["B"]) >= 2)
            plan["reinforce"] = counts["A"] > counts["B"] ? "A" : "B";
        if (w.at("phase") == "planted" && !leader.at("heardSite").empty())
            plan["reinforce"] = leader.at("heardSite");
    }
}
} // namespace esport
