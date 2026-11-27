#include "economy.hpp"
#include "grid_round.hpp"
#include "opening.hpp"
#include <algorithm>

namespace esport {
namespace {
Json tactic_reference(const Json &board) {
    Json result = Json::object();
    for (auto k : {"id", "revision", "name", "side", "buy"})
        result[k] = board.at(k);
    return result;
}
std::vector<std::string> categories(const std::string &buy) {
    if (buy == "Эко" || buy == "Пистолетная")
        return {buy};
    return {buy, "Оружейная"};
}
} // namespace
void OpeningMap::begin_live(Json &w, const Json &cfg) const {
    const auto grid = objectives_->grid();
    const auto now = w.at("tick").get<Tick>();
    for (const std::string side : {"T", "CT"}) {
        const auto is_coach = [&]() {
            for (auto &a : w.at("agents"))
                if (a.at("team") == side && a.at("appointed") == true)
                    return a.at("teamId") == w.at("coachTeamId");
            throw std::invalid_argument("Капитан не назначен");
        }();
        Json coach = is_coach ? w.at("call") : Json(nullptr), board = nullptr;
        // Ordered JSON can move top-level values when erasing an earlier key.
        // Take roster references only after consuming the queued call.
        if (is_coach && w.contains("nextBoard")) {
            board = w.at("nextBoard");
            w.erase("nextBoard");
            if (!board.empty())
                coach = board.at("buy") == "Эко" ? Json("Экономить") : Json(nullptr);
        }
        auto &roster = w.at("agents");
        auto it = std::find_if(roster.begin(), roster.end(), [&](const Json &a) {
            return a.at("team") == side && a.at("appointed") == true;
        });
        auto &captain = *it;
        std::string buy = grid ? grid_buy(w, cfg, side, coach)
                               : buy_decision(w, cfg, side, coach, nullptr, nullptr, nullptr)
                                     .at("scenario")
                                     .get<std::string>();
        if (!grid && !board.empty() && w.contains("previewBuy") && !w.at("previewBuy").empty())
            buy = w.at("previewBuy");
        if (is_coach && board.empty() && (coach.is_null() || coach == "Экономить") &&
            w.contains("playbook")) {
            const auto &book = w.at("playbook");
            for (auto &cat : grid ? std::vector<std::string>{categories(buy).back()} : categories(buy)) {
                auto key = side + "/" + cat;
                if (book.contains(key)) {
                    board = book.at(key);
                    break;
                }
            }
        }
        std::string site = (draw_rng(captain) >> 16) % 2 ? "B" : "A";
        if (coach == "Выход A")
            site = "A";
        if (coach == "Выход B")
            site = "B";
        const auto &skills =
            w.at("domain").at("players").at(captain.at("playerId").get<std::string>()).at("skills");
        std::string style = coach == "Ускориться" || int((draw_rng(captain) >> 16) % 100) <
                                                         20 + skills.at("aggression").get<double>() * .6
                                ? "Быстро"
                                : "Сбор";
        std::optional<std::string> planted;
        if (!board.empty())
            for (auto &steps : board.at("slots")) {
                auto plant = std::find_if(steps.begin(), steps.end(),
                                          [](const Json &s) { return s.at("kind") == "plant"; });
                if (plant != steps.end()) {
                    planted =
                        objectives_->site_at(Point{plant->at("x"), plant->at("y"), plant->value("z", 0.)});
                    if (!planted)
                        throw std::invalid_argument("Площадка назначенной тактики отсутствует");
                    site = *planted;
                    break;
                }
            }
        Json request = nullptr;
        if (!board.empty())
            request = w.contains("previewBuy") && !w.at("previewBuy").empty() ? w.at("previewBuy")
                                                                              : board.at("buy");
        Json strategy;
        int lane = 0;
        if (!grid) {
            strategy = buy_decision(w, cfg, side, coach, site, board, request);
            buy = strategy.at("scenario");
            auto choice = call(w, captain, buy, site, style, coach);
            site = planted ? *planted : choice.at(0).get<std::string>();
            style = choice.at(1);
            lane = choice.at(2);
        }
        auto reinforce =
            side == "CT" && (coach == "Выход A" || coach == "Выход B") ? Json(site) : Json(nullptr);
        auto orders = grid          ? grid->data.at("orders").at(side).at(site)
                      : side == "T" ? attack_orders(w, site, lane, style)
                                    : defense_orders(w, site, lane);
        Json plan = {{"site", site},
                     {"style", style},
                     {"buy", buy},
                     {"start", now},
                     {"review", now},
                     {"rotated", false},
                     {"orders", std::move(orders)},
                     {"captain", captain.at("id")},
                     {"reinforce", reinforce}};
        if (!grid)
            plan["lane"] = lane;
        if (!grid && side == "CT" && board.empty()) {
            auto predicted = coach.is_null() ? defensive_read(w, captain) : Json(nullptr);
            if (!predicted.is_null())
                site = predicted;
            plan["site"] = site;
            style = draft(w, captain, plan, predicted, reinforce);
        }
        if (!grid && side == "T" && board.empty() && (style == "Сбор" || style == "Контроль карты"))
            plan["probe"] = default_probe(w, plan, cfg);
        auto name = captain.at("name").get<std::string>();
        emit(w, "plan", name + " · " + style + ", " + site + " · " + buy, side)
            .update(Json{{"player", captain.at("id")}, {"site", site}, {"style", style}, {"buy", buy}});
        int l = w.at("score")[0], r = w.at("score")[1];
        for (auto &a : roster)
            if (a.at("team") == side) {
                a["liveStart"] = now;
                a["dayRoll"] = int((draw_rng(a) >> 16) % 17) - 8;
                a["pressure"] =
                    int(std::max(l, r) >= cfg.at("rules").at("half").get<int>() && std::abs(l - r) <= 2);
            }
        if (!board.empty()) {
            plan["board"] = board;
            emit(w, "board",
                 name + " вызывает «" + board.at("name").get<std::string>() + "» · в" +
                     board.at("revision").dump(),
                 side)["tactic"] = tactic_reference(board);
            for (auto &a : roster)
                if (a.at("team") == side) {
                    a["stepIndex"] = 0;
                    a["stepUntil"] = nullptr;
                    const auto &steps = board.at("slots").at(a.at("slot").get<int>());
                    if (std::ranges::any_of(steps, [](const Json &s) { return s.at("kind") == "plant"; }))
                        w.at("bomb")["carrier"] = a.at("id");
                    if (grid) {
                        Json wanted = Json::object();
                        for (auto &step : steps)
                            if (step.at("kind") == "throw") {
                                auto item = step.at("utility").get<std::string>();
                                wanted[item] = wanted.value(item, 0) + 1;
                            }
                        for (auto &[item, qty] : wanted.items()) {
                            int need = qty.get<int>() -
                                       std::count(a.at("utility").begin(), a.at("utility").end(), Json(item));
                            while (need-- > 0 && a.at("utility").size() < 2)
                                purchase_item(w, cfg, a, item);
                        }
                    }
                }
        }
        if (grid) {
            grid_purchase(w, cfg, side, buy, captain);
            w.at("plans")[side] = std::move(plan);
            continue;
        }
        for (const auto &a : roster)
            if (a.at("team") == side) {
                const auto id = a.at("id").get<std::string>();
                Json items = grenade_needs(w, cfg, a, site, board);
                if (collective_attack(w) && side == "T" && plan.contains("probe") &&
                    plan.at("probe").contains("stations") && plan.at("probe").at("scout") == id &&
                    (buy == "Полная" || buy == "Антиэко" || buy == "Бонусная")) {
                    plan.at("probe")["feint"] = true;
                    const auto decoy = std::find(items.begin(), items.end(), "Ложная");
                    if (decoy != items.end())
                        items.erase(decoy);
                    items.insert(items.begin(), "Ложная");
                    if (items.size() > 4)
                        items.erase(items.end() - 1);
                }
                if (plan.contains("opening")) {
                    const auto &opening = plan.at("opening"), job = opening.at("jobs").at(id);
                    auto &focus = opening.at("focus");
                    if (opening.at("quiet") == false &&
                        std::find(focus.begin(), focus.end(), job.at("zone")) != focus.end()) {
                        Json wanted = Json::array();
                        if (job.contains("gate"))
                            wanted = {job.at("role") == "страховка" ? "Свет" : "Огонь", "Дым"};
                        auto preferred = wanted;
                        for (auto &g : items)
                            if (std::find(preferred.begin(), preferred.end(), g) == preferred.end() &&
                                wanted.size() < 4)
                                wanted.push_back(g);
                        items = std::move(wanted);
                    }
                }
                strategy.at("needs")[id] = std::move(items);
            }
        plan["economy"] = strategy;
        buy_equipment(w, cfg, side, strategy, board);
        if (plan.contains("opening"))
            equip_defense(w, plan, cfg);
        w.at("plans")[side] = std::move(plan);
    }
    w["call"] = nullptr;
    w["phase"] = "live";
    w["deadline"] = plus_ticks(now, cfg.at("rules").at("live"));
}
} // namespace esport
