#include "grenades.hpp"
#include "economy.hpp"
#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <tuple>

namespace esport {
namespace {
using Items = std::vector<std::string>;
bool has(const Json &seq, const Json &value) { return std::find(seq.begin(), seq.end(), value) != seq.end(); }
bool pistol(const Json &cfg, const std::string &item) { return has(cfg.at("sidearms"), item); }
std::string primary(const Json &p, const Json &cfg) {
    const auto current = p.at("weapon").get<std::string>();
    if (!pistol(cfg, current))
        return current;
    const auto &other = p.at("holster");
    if (other.is_null() || pistol(cfg, other.at("weapon")))
        return {};
    return other.at("weapon");
}
Items required(const Json &a, const Json &board) {
    Items items;
    if (!board.empty())
        for (const auto &step : board.at("slots").at(a.at("slot").get<int>()))
            if (step.at("kind") == "throw")
                items.push_back(step.at("utility"));
    return items;
}
Items grenades_for(const Json &a, bool long_approach, const Json &board, bool revised) {
    Items options = required(a, board), extras;
    const int slot = a.at("slot");
    const auto role = a.at("playingRole");
    if (a.at("team") == "CT")
        extras = {slot < 2 ? "Огонь" : "Свет", "Дым"};
    else if (role == "support")
        extras = {"Дым", "Свет"};
    else if (role == "entry")
        extras = {"Свет", "HE"};
    else if (long_approach)
        extras = {"Дым", "Свет"};
    else
        extras = {"Свет", "Огонь"};
    if (revised && role == "lurker")
        extras.insert(extras.begin() + 1, "Ложная");
    if (role == "support")
        extras.insert(extras.end(), {"Свет", "HE"});
    else if (slot < 2)
        extras.push_back("HE");
    extras.insert(extras.end(), {"Дым", "Свет", a.at("team") == "CT" ? "Огонь" : "HE"});
    for (const auto &item : extras)
        if (std::count(options.begin(), options.end(), item) < (item == "Свет" ? 2 : 1))
            options.push_back(item);
    if (options.size() > 4)
        options.resize(4);
    return options;
}
// Counter subtraction emits all missing copies together, in first-seen order.
Items missing_items(const Items &required, const Json &carried) {
    Items result;
    std::set<std::string> seen;
    for (const auto &item : required)
        if (seen.insert(item).second) {
            auto n = std::count(required.begin(), required.end(), item) -
                     std::count(carried.begin(), carried.end(), item);
            if (n > 0)
                result.insert(result.end(), n, item);
        }
    return result;
}
int price(const Json &cfg, const std::string &item) {
    const auto &guns = cfg.at("weapons");
    return guns.contains(item) ? guns.at(item).at("price").get<int>() : cfg.at("prices").at(item).get<int>();
}
} // namespace
void equip_weapon(Json &a, const Json &item, const Json &cfg) {
    Json active = {{"weapon", a.at("weapon")}, {"ammo", a.at("ammo")}, {"reserve", a.at("reserve")}};
    bool secondary = pistol(cfg, item.at("weapon"));
    if (secondary == pistol(cfg, a.at("weapon"))) {
        a.update(item);
        a["reloadAt"] = 0;
    } else if (!secondary || (a.at("ammo") == 0 && a.at("reserve") == 0)) {
        a.update(item);
        a["holster"] = std::move(active);
        a["reloadAt"] = 0;
    } else
        a["holster"] = item;
}

Json grenade_needs(const Json& w,const Json& cfg,const Json& actor,const std::string& site,const Json& board) {
    return grenades_for(actor,
                        cfg.at("longApproaches").at(w.at("mapId").get<std::string>()).value(site, false),
                        board, spatial_grenades(w));
}
Json buy_decision(const Json &w, const Json &cfg, const std::string &side, const Json &call, const Json &site,
                  const Json &board, const Json &requested) {
    const auto &rules = cfg.at("rules");
    Json needs = Json::object(), limits = Json::object(), expected = Json::object();
    const bool long_approach =
        site.is_string() &&
        cfg.at("longApproaches").at(w.at("mapId").get<std::string>()).value(site.get<std::string>(), false);
    const std::string rifle = side == "T" ? "AK-47" : "M4A1-S", smg = side == "T" ? "MAC-10" : "MP9";
    const int cost = price(cfg, rifle), next = cost + 1000 + price(cfg, "Дым") + price(cfg, "Свет");
    std::map<std::string, int> wallets, reserves, cash;
    int armed = 0, light = 0, club = -1, spare = 0;
    for (const auto &a : w.at("agents"))
        if (a.at("team") == side) {
            club = a.at("club");
            auto items = grenades_for(a, long_approach, board, spatial_grenades(w));
            std::string id = a.at("id");
            needs[id] = items;
            int needed = (a.at("armor") < 45 ? 650 : 0) + (a.at("helmet") == false ? 350 : 0) +
                         (side == "CT" && a.at("slot") < 2 && a.at("kit") == false ? 400 : 0);
            for (const auto &item : missing_items(items, a.at("utility")))
                needed += price(cfg, item);
            int money = a.at("cash");
            wallets[id] = money - needed;
            cash[id] = money;
            const auto gun = primary(a, cfg);
            armed += !gun.empty();
            light += gun == "MP9" || gun == "MAC-10" || gun == "Nova";
        }
    if (club < 0)
        throw std::invalid_argument("Отсутствует состав для закупки");
    const int income = std::min(rules.at("lossMax").get<int>(),
                                rules.at("lossBase").get<int>() +
                                    rules.at("lossStep").get<int>() * w.at("streak").at(club).get<int>());
    int free_rifles = 0;
    for (const auto &[id, money] : cash) {
        reserves[id] = std::min(money, std::max(0, next - income));
        spare += money - reserves[id];
        free_rifles += std::max(0, wallets[id] - reserves[id]) / cost;
    }
    auto affordable = [&](int unit) {
        int possible = armed;
        for (const auto &[id, wallet] : wallets)
            possible += std::max(0, wallet) / unit;
        return std::min(int(cash.size()), possible);
    };
    int rifles = affordable(cost);
    Json intel = w.value("opponentEconomy", Json::object()).value(side, Json::object());
    int likely = 0;
    for (const auto &r : intel)
        if (!r.at("saved").is_null() || r.at("balance") >= price(cfg, side == "T" ? "M4A1-S" : "AK-47"))
            ++likely;
    const bool weak = intel.size() == 5 && likely <= 1;
    int n = w.at("round"), reg = rules.at("half"),
        half = n <= 2 * reg ? reg : rules.at("overtimeHalf").get<int>();
    int remaining = half - (n - 1) % half, target = n <= 24 ? reg + 1 : 16 + 3 * ((n - 25) / 6);
    bool must = remaining == 1 || w.at("score").at(1 - club) >= target - 1;
    const std::set<std::string> scenarios{"Пистолетная", "Эко",     "Частичная", "Форс",
                                          "Полная",      "Антиэко", "Бонусная"};
    std::string budget;
    Json context = nullptr;
    if (requested.is_string() && scenarios.contains(requested.get<std::string>()))
        budget = requested;
    else if (n == 1 || n == reg + 1)
        budget = "Пистолетная";
    else if (call == "Экономить")
        budget = "Эко";
    else if ((weak && affordable(price(cfg, smg)) >= 4) || rifles >= 4)
        budget = "Полная";
    else if (must || (rifles >= 3 && (weak || light >= 2)))
        budget = "Форс";
    else if (spare >= 2 * price(cfg, "Свет") + price(cfg, "Дым"))
        budget = "Частичная";
    else
        budget = "Эко";
    if (requested == "Антиэко" || requested == "Бонусная") {
        context = requested;
        budget = requested == "Антиэко" ? "Полная" : "Частичная";
    } else if (budget != "Пистолетная" && budget != "Эко" && weak)
        context = "Антиэко";
    else if (budget != "Пистолетная" && budget != "Эко" && light >= 2 && intel.size() == 5 && likely >= 3 &&
             free_rifles < light && !must)
        context = "Бонусная";
    if (context == "Бонусная")
        budget = "Частичная";
    // The ledger retains squad order through side switches.
    for (const auto &a : w.at("agents"))
        if (a.at("team") == side) {
            std::string id = a.at("id");
            int limit = budget == "Эко" ? 0 : budget == "Частичная" ? cash[id] - reserves[id] : cash[id];
            limits[id] = limit;
            expected[id] = std::min(rules.at("cap").get<int>(), cash[id] - limit + income);
        }
    return Json{{"budget", budget},
                {"context", context},
                {"scenario", context.is_null() ? Json(budget) : context},
                {"limit", limits},
                {"needs", needs},
                {"lossIncome", income},
                {"roundsLeft", remaining},
                {"opponentGuns", intel.empty() ? Json(nullptr) : Json(likely)},
                {"nextTarget", next},
                {"expectedAfterLoss", expected}};
}

bool purchase_item(Json &w, const Json &cfg, Json &payer, const std::string &item, Json *gift) {
    int cost = price(cfg, item);
    if (payer.at("cash") < cost || (item == "Шлем" && (payer.at("armor") == 0 || payer.at("helmet") == true)))
        return false;
    auto &recipient = gift ? *gift : payer;
    pay(w, payer, -cost, "Покупка · " + item, cfg.at("rules").at("cap"));
    const auto &guns = cfg.at("weapons");
    if (guns.contains(item)) {
        int mag = guns.at(item).at("mag");
        equip_weapon(recipient, Json{{"weapon", item}, {"ammo", mag}, {"reserve", mag * 3}}, cfg);
    } else if (item == "Броня")
        payer["armor"] = 100;
    else if (item == "Шлем")
        payer["helmet"] = true;
    else if (item == "Набор")
        payer["kit"] = true;
    else
        payer.at("utility").push_back(item);
    auto text = payer.at("name").get<std::string>() + " · " + item;
    if (gift)
        text += " для " + gift->at("name").get<std::string>();
    emit(w, "buy", text, payer.at("team"))
        .update(Json{
            {"player", payer.at("id")}, {"item", item}, {"recipient", recipient.at("id")}, {"price", cost}});
    return true;
}
void buy_equipment(Json &w, const Json &cfg, const std::string &side, const Json &strategy,
                   const Json &board) {
    const auto &budget = strategy.at("budget");
    if (budget == "Эко")
        return;
    const auto &context = strategy.at("context"), needs = strategy.at("needs");
    auto funds = strategy.at("limit").get<std::map<std::string, int>>();
    std::vector<Json *> squad;
    for (auto &a : w.at("agents"))
        if (a.at("team") == side)
            squad.push_back(&a);
    auto purchase = [&](Json &payer, const std::string &item, Json *gift = nullptr) {
        auto &wallet = funds.at(payer.at("id").get<std::string>());
        int cost = price(cfg, item);
        if (wallet < cost || !purchase_item(w, cfg, payer, item, gift))
            return false;
        wallet -= cost;
        return true;
    };
    auto grenades = [&](Json &a, const Items &required, bool legacy = false) {
        auto &inventory = a.at("utility");
        for (auto &g : missing_items(required, inventory))
            if (inventory.size() < 4 &&
                std::count(inventory.begin(), inventory.end(), g) < (legacy || g == "Свет" ? 2 : 1))
                purchase(a, g);
    };
    auto protect = [&](Json &a) {
        if (a.at("armor") < 45)
            purchase(a, "Броня");
    };
    if (!board.empty())
        for (auto *a : squad)
            grenades(*a, required(*a, board), board.at("format") == 1);
    if (budget == "Пистолетная") {
        for (auto *a : squad) {
            bool kit_slot = side == "CT" && a->at("slot") == 1;
            if (kit_slot && a->at("kit") == false)
                purchase(*a, "Набор");
            if (a->at("playingRole") == "support" || kit_slot)
                grenades(*a, needs.at(a->at("id").get<std::string>()).get<Items>());
            protect(*a);
        }
        return;
    }
    const std::string rifle = side == "T" ? "AK-47" : "M4A1-S", smg = side == "T" ? "MAC-10" : "MP9";
    std::vector<Json *> unarmed;
    for (auto *a : squad) {
        protect(*a);
        if (primary(*a, cfg).empty())
            unarmed.push_back(a);
    }
    const auto wallet = [&](Json *a) { return funds.at(a->at("id").get<std::string>()); };
    auto priority = [&](Json *a) {
        const auto &r = a->at("playingRole");
        return std::tuple{r != "entry" && r != "awper", wallet(a), a->at("slot").get<int>()};
    };
    std::stable_sort(unarmed.begin(), unarmed.end(),
                     [&](auto a, auto b) { return priority(a) < priority(b); });
    for (std::size_t i = 0; i < unarmed.size(); ++i) {
        auto *a = unarmed[i];
        Items choices{rifle, smg};
        if (context == "Антиэко" && a->at("playingRole") != "awper")
            std::swap(choices[0], choices[1]);
        if (a->at("playingRole") == "awper" && budget == "Полная" && context != "Антиэко") {
            int available = 0;
            for (const auto &[id, n] : funds)
                available += n;
            if (available >= 4750 + price(cfg, rifle) * int(unarmed.size() - i - 1) + 500)
                choices.insert(choices.begin(), "AWP");
        }
        if (budget == "Форс" || budget == "Частичная")
            choices.push_back("Desert Eagle");
        for (const auto &item : choices) {
            auto donors = squad;
            auto key = [&](Json *p) {
                return std::tuple{wallet(p) < price(cfg, item), p != a, -wallet(p), p->at("slot").get<int>()};
            };
            std::stable_sort(donors.begin(), donors.end(), [&](auto l, auto r) { return key(l) < key(r); });
            if (std::ranges::any_of(donors, [&](auto p) { return purchase(*p, item, p != a ? a : nullptr); }))
                break;
        }
    }
    auto support = squad;
    auto key = [](Json *a) { return std::pair{a->at("playingRole") != "support", a->at("slot").get<int>()}; };
    std::stable_sort(support.begin(), support.end(), [&](auto l, auto r) { return key(l) < key(r); });
    for (auto *a : support) {
        if (a->at("armor") != 0 && a->at("helmet") == false && (budget == "Полная" || context == "Антиэко"))
            purchase(*a, "Шлем");
        if (side == "CT" && a->at("kit") == false &&
            std::count_if(squad.begin(), squad.end(), [](auto p) { return p->at("kit") == true; }) < 2)
            purchase(*a, "Набор");
        grenades(*a, needs.at(a->at("id").get<std::string>()).get<Items>());
    }
    if (budget == "Полная" && context.is_null() &&
        std::ranges::all_of(squad, [&](auto a) { return !primary(*a, cfg).empty(); })) {
        for (auto *a : squad) {
            auto gun = primary(*a, cfg);
            if (gun != "MP9" && gun != "MAC-10" && gun != "Nova" && gun != "Negev")
                continue;
            int reserve =
                std::max(0, strategy.at("nextTarget").get<int>() - strategy.at("lossIncome").get<int>());
            if (wallet(a) >= price(cfg, rifle) + reserve)
                purchase(*a, rifle);
        }
    }
}
} // namespace esport
