#include "coaching.hpp"
#include "round_rules.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>

namespace esport {
std::uint32_t draw_rng(Json &actor) {
    auto next = actor.at("rng").get<std::uint32_t>() * 1664525u + 1013904223u;
    actor.at("rng") = next;
    return next;
}
namespace {
using Names = std::set<std::string>;
std::string name(const Json &j, const char *key) { return j.at(key).get<std::string>(); }
int number(const Json &j, const char *key) { return j.at(key).get<int>(); }
void add(Json &value, int delta) { value = value.get<int>() + delta; }
bool has(const Json &entries, const Json &value) {
    return std::find(entries.begin(), entries.end(), value) != entries.end();
}

} // namespace
void pay(Json &w, Json &a, int delta, const std::string &reason, int cap) {
    const int before = number(a, "cash"), after = std::min(cap, before + delta);
    if (after < 0)
        throw std::invalid_argument("Недостаточно средств");
    int amount = after - before;
    auto &event = emit(w, "money",
                       name(a, "name") + " · " + reason + " (" + (amount >= 0 ? "+" : "") +
                           std::to_string(amount) + "$)",
                       a.at("team"));
    event.update(Json{{"player", a.at("id")}, {"amount", amount}, {"balance", after}, {"reason", reason}});
    a.at("cash") = after;
    if (delta<0 && reason.starts_with("Покупка")) add(w.at("stats").at(name(a,"id")).at("spent"),-amount);
}
namespace {
int loss_income(const Json &rules, int level) {
    return std::min(number(rules, "lossMax"), number(rules, "lossBase") + number(rules, "lossStep") * level);
}
void append_limited(Json &list, Json item, std::size_t limit) {
    list.push_back(std::move(item));
    if (list.size() > limit)
        list.erase(list.begin(), list.end() - limit);
}

void update_accounts(Json &w, const Json &cfg, const std::string &winner, const std::string &reason,
                     int win_reward) {
    const auto &guns = cfg.at("weapons");
    const auto &rules = cfg.at("rules");
    Names dead;
    for (const auto &k : w.at("kills"))
        dead.insert(name(k, "target"));
    for (std::string side : {"T", "CT"}) {
        std::string rival = side == "T" ? "CT" : "T";
        std::vector<std::string> roster;
        int club = 0;
        for (const auto &a : w.at("agents"))
            if (a.at("team") == rival) {
                roster.push_back(name(a, "id"));
                club = number(a, "club");
            }
        int income = rival == winner ? win_reward : loss_income(rules, w.at("streak").at(club));
        if (rival == "T" && reason == "Обезвреживание")
            income += 600;
        std::map<std::string, std::string> known;
        const auto plan = w.at("plans").value(side, Json::object());
        const auto sightings = plan.value("economicSightings", Json::object());
        for (const auto &[id, sighting] : sightings.items())
            known[id] = name(sighting, "weapon");
        std::map<std::string, int> reward;
        for (const auto &k : w.at("kills")) {
            std::string shooter = name(k, "player"), gun = name(k, "weapon");
            if (std::find(roster.begin(), roster.end(), shooter) == roster.end())
                continue;
            if (guns.contains(gun))
                known[shooter] = gun;
            if (k.at("enemy") == true) {
                if (rival == "CT")
                    income += 50;
                reward[shooter] += guns.contains(gun) ? number(guns.at(gun), "reward") : 300;
            }
        }
        auto &accounts = w["opponentEconomy"][side];
        if (accounts.is_null())
            accounts = Json::object();
        for (const auto &id : roster) {
            Json prior = accounts.value(id, Json{{"balance", rules.at("startMoney")}, {"saved", nullptr}});
            auto gun = known.contains(id) ? Json(known.at(id)) : prior.at("saved");
            int bought = gun.is_string() && guns.contains(gun.get<std::string>()) && gun != prior.at("saved")
                             ? number(guns.at(gun.get<std::string>()), "price")
                             : 0;
            int estimate = std::max(0, number(prior, "balance") - bought);
            const int rifle = number(guns.at(rival == "T" ? "AK-47" : "M4A1-S"), "price");
            if (gun.is_null() && estimate >= rifle + 650)
                estimate -= rifle;
            estimate = std::max(0, estimate - 1000);
            int paid = rival == "T" && reason == "Время" && !dead.contains(id) ? 0 : income;
            accounts[id] =
                Json{{"balance", std::min(number(rules, "cap"), estimate + paid + reward[id])},
                     {"saved", !dead.contains(id) && !has(cfg.at("sidearms"), gun) ? gun : Json(nullptr)}};
        }
    }
}
} // namespace

void settle_round(Json &w, const Json &cfg, const std::string &side, const std::string &reason) {
    if (side != "T" && side != "CT")
        throw std::invalid_argument("Неизвестная сторона");
    const Json &rules = cfg.at("rules");
    std::map<std::string, std::string> teams;
    std::map<std::string, int> clubs;
    Names ct;
    Json heard = nullptr;
    for (const auto &a : w.at("agents")) {
        const auto s = name(a, "team"), id = name(a, "teamId");
        if (teams.contains(s) && teams[s] != id)
            throw std::invalid_argument("Сторона раунда не привязана к одной команде");
        teams[s] = id;
        clubs[s] = number(a, "club");
        if (s == "CT") {
            ct.insert(name(a, "id"));
            if (heard.is_null() && !a.at("heardSite").is_null())
                heard = a.at("heardSite");
        }
    }
    const auto winner_id = teams.at(side);
    const auto winner = clubs.at(side);
    const auto title = name(w.at("domain").at("teams").at(winner_id), "name");
    add(w.at("scoreByTeam").at(winner_id), 1);
    w.at("score").at(winner) = w.at("scoreByTeam").at(winner_id);
    emit(w, "round_end", title + " · " + reason)
        .update(Json{{"winner", winner}, {"winnerTeamId", winner_id}, {"side", side}, {"reason", reason}});
    const Tick round_event = w.at("serial");
    if (w.contains("mapId") && w.at("plans").contains("T")) {
        append_limited(w["siteHistory"][teams.at("T")],
                       Json::array({w.at("plans").at("T").at("site"), side == "T"}), 6);
        append_limited(w["defensiveHistory"][teams.at("CT")], heard, 4);
    }
    if (w.contains("mapId") && !w.contains("opponentEconomy"))
        w["opponentEconomy"] = Json::object();
    const auto &kills = w.at("kills");
    const int reward =
        number(rules, (reason == "Взрыв C4" || reason == "Обезвреживание") ? "objectiveWin" : "win");
    const int cap = number(rules, "cap");
    for (auto &a : w.at("agents")) {
        auto &player = w.at("domain").at("players").at(name(a, "playerId"));
        const auto &skills = player.at("skills");
        const auto load =
            std::nearbyint(number(a, "movingTicks") * (150. - number(skills, "endurance")) / 2100);
        player["fatigue"] =
            std::clamp(number(player, "fatigue") + int(load) - 1 - number(skills, "recovery") / 15, 0, 100);
        bool contributed = number(a, "hp") > 0 || std::ranges::any_of(kills, [&](const auto &k) {
                               const auto &id = a.at("id");
                               return (id == k.at("player") && k.at("enemy") == true) ||
                                      has(k.at("assists"), id) || id == k.at("trade");
                           });
        if (contributed)
            add(w.at("stats").at(name(a, "id")).at("kast"), 1);
        if (a.at("team") == side)
            pay(w, a, reward, "Победа", cap);
        else if (!(a.at("team") == "T" && number(a, "hp") && reason == "Время")) {
            pay(w, a, loss_income(rules, w.at("streak").at(number(a, "club"))), "Поражение", cap);
            if (a.at("team") == "T" && !w.at("bomb").at("site").is_null())
                pay(w, a, w.contains("mapId") ? 600 : number(rules, "plantBonus"),
                    "Установка в проигранном раунде", cap);
        }
    }
    int bonus = 0;
    for (const auto &k : kills)
        if (k.at("enemy") == true && ct.contains(name(k, "player")))
            bonus += 50;
    if (w.contains("mapId") && bonus)
        for (auto &a : w.at("agents"))
            if (ct.contains(name(a, "id")))
                pay(w, a, bonus, "Командная награда за устранения CT", cap);
    if (w.contains("mapId"))
        update_accounts(w, cfg, side, reason, reward);
    if (w.at("clutch").contains(side))
        add(w.at("stats").at(w.at("clutch").at(side).get<std::string>()).at("clutches"), 1);
    Json economy = {{"T", 0}, {"CT", 0}};
    for (const auto &e : w.at("events"))
        if (e.at("kind") == "buy")
            add(economy.at(name(e, "team")), number(e, "price"));
    Json result = {{"round", w.at("round")},
                   {"winner", winner},
                   {"winnerTeamId", winner_id},
                   {"side", side},
                   {"reason", reason},
                   {"score", w.at("score")},
                   {"scoreByTeam", w.at("scoreByTeam")},
                   {"duration", w.at("tick").get<Tick>() - w.at("roundStart").get<Tick>()},
                   {"economy", economy}};
    for (const auto &plan : w.at("plans"))
        if (plan.contains("board") && !plan.at("board").empty()) {
            Json tactic = Json::object();
            for (const auto &key : {"id", "revision", "name", "side", "buy"})
                tactic[key] = plan.at("board").at(key);
            result["tactic"] = std::move(tactic);
        }
    w.at("history").push_back(std::move(result));
    auto &streak = w.at("streak");
    streak.at(winner) = w.contains("mapId") ? std::max(0, streak.at(winner).get<int>() - 1) : 0;
    streak.at(1 - winner) = w.contains("mapId") ? std::min(4, streak.at(1 - winner).get<int>() + 1)
                                                : streak.at(1 - winner).get<int>() + 1;
    const int n = number(w, "round"), half = number(rules, "half"), ot = number(rules, "overtimeHalf");
    const int target = n <= half * 2 ? half + 1 : half + ot * (1 + (n - 2 * half - 1) / (2 * ot)) + 1;
    for (auto &a : w.at("agents")) round_emotion(w,a,a.at("team")==side,target,round_event);
    bool finished = w.at("scoreByTeam").at(winner_id) >= target;
    w["phase"] = finished ? "finished" : "result";
    w["deadline"] = plus_ticks(w.at("tick"), number(rules, "result"));
    w["action"] = nullptr;
    if (finished) {
        w["pending"] = false;
        w["winnerTeamId"] = winner_id;
        emit(w, "match_end", title + " выиграл BO1")
            .update(Json{{"winner", winner}, {"winnerTeamId", winner_id}});
    }
}
} // namespace esport

namespace esport {
// Rows retain source order. The selected spawn depends on seed, round and slot.
void start_round(Json &w, const Json &cfg, const Json &spawns) {
    const auto &rules = cfg.at("rules");
    const auto &guns = cfg.at("weapons");
    const auto n = number(w, "round") + 1;
    const auto half = number(rules, "half"), ot = number(rules, "overtimeHalf");
    const int period = n <= 2 * half ? (n - 1) / half : 2 + (n - 1 - 2 * half) / ot;
    const int swaps = n <= 2 * half ? period : 1 + ((n - 1 - 2 * half) / ot + 1) / 2;
    const bool reset = n == 1 || n == half + 1 || (n > 2 * half && (n - 1 - 2 * half) % ot == 0);
    if (!w.at("events").empty())
        w.at("archive").push_back(std::move(w.at("events")));
    const auto array = Json::array(), obj = Json::object();
    const auto now = w.at("tick").get<Tick>();
    w.update(Json{{"round", n},
                  {"phase", "freeze"},
                  {"deadline", plus_ticks(now, number(rules, "freeze"))},
                  {"events", array},
                  {"action", nullptr},
                  {"bomb", Json{{"carrier", nullptr}, {"site", nullptr}, {"x", nullptr}, {"y", nullptr}}},
                  {"effects", array},
                  {"recentEffects", array},
                  {"traces", array},
                  {"messages", array},
                  {"kills", array},
                  {"groundWeapons", array},
                  {"plans", obj},
                  {"clutch", obj},
                  {"roundStart", now}});
    if (reset) {
        w["streak"] = w.contains("mapId") ? Json::array({1, 1}) : Json::array({0, 0});
        if (w.contains("mapId"))
            w["opponentEconomy"] = obj;
    }
    for (auto &a : w.at("agents")) {
        initialize_mind(w,a);
        a.erase("coachOrder");
        const std::string side =
            ((a.at("teamId") == w.at("firstAttackTeamId")) != bool(swaps % 2)) ? "T" : "CT";
        const auto slot = number(a, "slot");
        const auto &choices = spawns.at(side);
        if (choices.empty())
            throw std::invalid_argument("Отсутствуют позиции старта раунда");
        const auto size = static_cast<std::int64_t>(choices.size());
        // Reduce before adding to preserve large and negative seeds.
        const auto select = ((w.at("seed").get<std::int64_t>() % size + n + slot) % size + size) % size;
        const auto &spawn = choices.at(w.contains("mapId") ? select : slot);
        const auto &p = spawn.at(0);
        if (w.contains("mapId"))
            a.update(Json{{"z", p.at(2)},
                          {"navArea", spawn.at(2)},
                          {"waypoint", 0},
                          {"blockedTicks", 0},
                          {"inspectedSites", obj},
                          {"routeReports", obj},
                          {"lastRouteReport", -100},
                          {"useTarget", nullptr},
                          {"useFloor", nullptr},
                          {"checkContact", nullptr},
                          {"checkPosition", nullptr},
                          {"shelter", nullptr},
                          {"coverUntil", 0},
                          {"coverReview", 0},
                          {"bombSearch", nullptr},
                          {"coveredDefuser", nullptr},
                          {"coverPoint", nullptr},
                          {"revisedApproach", nullptr},
                          {"rendezvous", nullptr},
                          {"plantCover", nullptr},
                          {"plantCheck", nullptr},
                          {"watchDevice", nullptr},
                          {"heardUse", -1000},
                          {"seenDevice", nullptr},
                          {"beepBearing", nullptr},
                          {"plantCue", nullptr},
                          {"leftScreen", false},
                          {"sectorReview", nullptr},
                          {"incoming", nullptr},
                          {"pressureCall", nullptr},
                          {"nextPressureCall", 0},
                          {"sectorCalls", obj},
                          {"squadPressure", obj},
                          {"screenedOpening", false},
                          {"friendlyUtility", array}});
        for (auto key :
             {"confirmedHit",    "pendingFlash",     "flashPulses",     "flashLevel",      "flashAssistOwner",
              "resumeFlashLook", "flashWarnings",    "flashImpairedAt", "flashImpairedBy", "flashWarning",
              "routeIssued",     "feintThrown",     "plantSpot",       "attackGate",      "audioCalls",      "lastDutyFeedback", "postWatch",       "decision",        "lastReloadBreak",
              "groupDuty",       "groupLead",        "groupInboxTick",  "declinedSupport", "sentContacts",
              "sentFeedback",    "peerCalls",        "crossingCalls",   "openingThrows",   "pushFlash"})
            a.erase(key);
        if (w.contains("agentPolicy")) {
            a.erase("lastRefusal");
            if (!w.contains("mapId")) {
                a.erase("shelter");
                a.erase("coverReview");
                a.erase("blockedStep");
                a.erase("boardFailures");
            }
        }
        if (reset || a.at("hp") == 0) {
            a.update(Json{{"weapon", side == "T" ? "Glock" : "USP"},
                          {"holster", nullptr},
                          {"armor", 0},
                          {"helmet", false},
                          {"kit", false},
                          {"utility", array}});
        } else if (!a.at("holster").is_null()) {
            const auto spare = name(a.at("holster"), "weapon");
            bool primary = !has(cfg.at("sidearms"), spare);
            auto holstered = primary ? name(a, "weapon") : spare;
            auto mag = number(guns.at(holstered), "mag");
            a["holster"] = Json{{"weapon", holstered}, {"ammo", mag}, {"reserve", mag * 3}};
            if (primary)
                a["weapon"] = spare;
        }
        if (reset) {
            a["team"] = side;
            pay(w, a, number(rules, n <= 2 * half ? "startMoney" : "overtimeMoney") - number(a, "cash"),
                "Старт половины", number(rules, "cap"));
        }
        const auto mag = number(guns.at(name(a, "weapon")), "mag");
        a.update(Json{{"team", side},
                      {"x", p.at(0)},
                      {"y", p.at(1)},
                      {"hp", 100},
                      {"status", "Подготовка"},
                      {"heading", spawn.at(1)},
                      {"ammo", mag},
                      {"reserve", mag * 3},
                      {"visible", array},
                      {"knowledge", obj},
                      {"path", array},
                      {"dest", array},
                      {"attackers", obj},
                      {"blind", 0},
                      {"ready", 0},
                      {"throwAt", 0},
                      {"reloadAt", 0},
                      {"lastShot", -100},
                      {"burst", 0},
                      {"target", nullptr},
                      {"heardSite", nullptr},
                      {"saving", nullptr},
                      {"approached", nullptr},
                      {"lastMove", -100},
                      {"lastHurt", -100},
                      {"previousTarget", nullptr},
                      {"observedSpeed", 0},
                      {"movingTicks", 0},
                      {"liveStart", now},
                      {"dayRoll", 0},
                      {"pressure", 0},
                      {"stepReady", 0},
                      {"tradeTarget", nullptr},
                      {"tradeUntil", 0}});
        if (side == "T" && slot == 2)
            w.at("bomb")["carrier"] = a.at("id");
    }
    emit(w, "round_start", "Раунд " + std::to_string(n) + " · закупка")
        .update(Json{{"period", period}, {"reset", reset}});
}
} // namespace esport
