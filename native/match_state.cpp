#include "match_state.hpp"
#include "economy.hpp"
#include "navigation.hpp"
#include "observation.hpp"
#include "round_rules.hpp"
#include "tactic_execution.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <limits>
#include <mutex>
#include <stdexcept>

namespace esport {

Tick plus_ticks(Tick tick, Tick offset) {
    if (offset < 0 || tick < 0 || tick > std::numeric_limits<Tick>::max() - offset)
        throw std::invalid_argument("Invalid match clock");
    return tick + offset;
}
Point position(const Json &agent) {
    return {agent.at("x").get<double>(), agent.at("y").get<double>(), agent.value("z", 0.)};
}
Json &emit(Json &state, const std::string &kind, const std::string &text, Json side) {
    auto id = plus_ticks(state.at("serial").get<Tick>(), 1);
    state.at("events").push_back(Json{{"id", id},
                                      {"round", state.at("round")},
                                      {"tick", state.at("tick")},
                                      {"kind", kind},
                                      {"text", text},
                                      {"team", std::move(side)}});
    state.at("serial") = id;
    return state.at("events").back();
}
namespace {
std::string team_side(const Json &agents, const std::string &team) {
    for (const auto &a : agents)
        if (a.at("teamId") == team)
            return a.at("team").get<std::string>();
    throw std::invalid_argument("Сторона команды отсутствует");
}
bool has_value(const Json &v) {
    if (v.is_boolean())
        return v.get<bool>();
    if (v.is_number())
        return v.get<double>() != 0;
    if (v.is_string())
        return !v.get_ref<const std::string &>().empty();
    return !v.is_null() && !v.empty();
}
} // namespace

class MatchState::Impl {
  public:
    Json state, config, spawns;
    std::unique_ptr<Combat> combat;
    std::shared_ptr<const Objectives> objectives;
    std::string rules;
    std::set<std::string> calls;
    int freeze;
    mutable std::mutex mutex;
    Impl(const std::string &checkpoint, std::string current_rules, const std::set<std::string> &old_rules,
         std::set<std::string> commands, int freeze_ticks, int build, const std::string &rulebook)
        : state(Json::parse(checkpoint)), config(Json::parse(rulebook)), rules(std::move(current_rules)),
          calls(std::move(commands)), freeze(freeze_ticks) {
        if (freeze <= 0 || state.at("map_version") != build || state.at("checkpointVersion") != 7 ||
            !(state.at("rules") == rules || old_rules.contains(state.at("rules").get<std::string>())))
            throw std::invalid_argument("Несовместимая версия сохранения подробного матча");
        if (!state.at("agents").is_array() || state.at("agents").size() != 10 ||
            !state.at("events").is_array() || !state.at("messages").is_array() ||
            state.at("tick").get<Tick>() < 0)
            throw std::invalid_argument("Некорректное состояние матча");
        std::set<std::string> ids;
        for (const auto &a : state.at("agents")) {
            if (!ids.insert(a.at("id").get<std::string>()).second || !a.at("knowledge").is_object())
                throw std::invalid_argument("Некорректное состояние игрока");
        }
    }

    void enter_timeout(Json &w) const {
        const auto coach = w.at("coachTeamId").get<std::string>();
        const auto name = w.at("domain").at("teams").at(coach).at("name").get<std::string>();
        int remaining = w.at("remaining");
        if (remaining <= 0)
            throw std::invalid_argument("Все три тайм-аута использованы");
        Json feedback = Json::array();
        for (const auto &a : w.at("agents"))
            if (a.at("teamId") == coach && has_value(a.at("evidence"))) {
                Json item = {{"player", a.at("name")}};
                item.update(a.at("evidence"));
                feedback.push_back(std::move(item));
            }
        w["phase"] = "timeout";
        w["pending"] = false;
        w["remaining"] = remaining - 1;
        w["feedback"] = std::move(feedback);
        emit(w, "timeout", name + " берёт тактический тайм-аут");
    }
    void authorize(const Json &w) const {
        const auto coach = w.at("coachTeamId").get<std::string>();
        const auto &domain = w.at("domain");
        const auto &club = domain.at("teams").at(coach);
        const auto &authority = domain.at("authority");
        if (club.at("organization") != authority.at("organization") ||
            (authority.at("mode") != "manager" && authority.at("mode") != "owner"))
            throw std::invalid_argument("Недостаточно полномочий в организации");
    }

    void apply_command(Json &w, const std::string &kind, const std::string &value) const {
        authorize(w);
        const auto coach = w.at("coachTeamId").get<std::string>();
        const std::string phase = w.at("phase"), name = w.at("domain").at("teams").at(coach).at("name");
        if (phase == "finished")
            throw std::invalid_argument("Матч завершён");
        if (kind == "timeout") {
            int remaining = w.at("remaining");
            if (remaining <= 0 || w.at("pending") == true || phase == "timeout")
                throw std::invalid_argument("Тайм-аут недоступен");
            if (phase == "freeze") {
                enter_timeout(w);
            } else {
                w["pending"] = true;
                emit(w, "request", name + " запросил тайм-аут на следующий раунд");
            }
        } else if (phase != "timeout")
            throw std::invalid_argument("Колл разрешён только в собственный тактический тайм-аут");
        else if (kind == "call" && calls.contains(value)) {
            w.erase("nextBoard");
            w["call"] = value;
            emit(w, "call", "Указание на следующий раунд · " + value, team_side(w.at("agents"), coach));
        } else if (kind == "resume") {
            w["phase"] = "freeze";
            w["deadline"] = plus_ticks(w.at("tick"), freeze);
            emit(w, "resume", "Тайм-аут завершён");
        } else
            throw std::invalid_argument("Неизвестное указание");
    }

    void deliver(const Json &w, Json &a, const Json &m, Tick now, Tick &review) const {
        const auto sender = m.at("sender").get<std::string>();
        if (m.contains("crossing")) {
            const auto &call = m.at("crossing");
            auto key = sender + (call.contains("feedback") && has_value(call.at("feedback")) ? "/order" : "");
            auto &calls = a["sectorCalls"];
            if (!calls.contains(key) || calls.at(key).at("tick") <= call.at("tick"))
                calls[key] = call;
        } else if (m.contains("pressure")) {
            const auto &call = m.at("pressure");
            a["squadPressure"][sender] = call;
            if (distance(position(a), call.at("origin").get<Point>()) < 35 &&
                (!a.contains("pressureCall") || !has_value(a.at("pressureCall")) ||
                 call.at("tick") > a.at("pressureCall").at("tick")))
                a["pressureCall"] = call;
        } else if (m.contains("friendlyUtility")) {
            auto items = a.value("friendlyUtility", Json::array());
            items.erase(
                std::remove_if(items.begin(), items.end(), [&](const Json &p) { return p.at("end") < now; }),
                items.end());
            items.push_back(m.at("friendlyUtility"));
            a["friendlyUtility"] = std::move(items);
        } else if (m.contains("blockedSite"))
            a["routeReports"][sender] = Json::array({m.at("blockedSite"), now});
        else if (m.contains("device")) {
            a["seenDevice"] = m.at("device");
            a["heardSite"] = m.at("device").at("site");
        } else if (m.contains("site"))
            a["heardSite"] = m.at("site");
        else {
            auto sight = m.at("sight");
            auto id = sight.at("id").get<std::string>();
            const auto &knowledge = a.at("knowledge");
            const Json *old = knowledge.contains(id) ? &knowledge.at(id) : nullptr;
            if (sight.at("tick") <= (old ? old->value("tick", Tick{-1}) : -1))
                return;
            if (sight.at("source") != "Граната" && sight.at("source") != "Слух")
                sight["source"] = "Радио";
            if (a.at("team") == "CT" && w.at("phase") == "live") {
                sight["reporter"] = sender;
                if (a.at("id") == w.at("plans").at("CT").at("captain") && sight.at("source") == "Радио" &&
                    (!old || (sight.value("carryingC4", false) && !old->value("carryingC4", false)) ||
                     sight.value("groupSize", 1) > old->value("groupSize", 1))) {
                    const auto player = a.at("playerId").get<std::string>();
                    const auto &domain = w.at("domain");
                    const auto &skill = domain.at("players").at(player).at("skills");
                    int chemistry = 0;
                    for (const auto &s : w.at("agents"))
                        if (s.at("id") == sender) {
                            auto p = s.at("playerId").get<std::string>();
                            chemistry = domain.at("chemistry")
                                            .value(std::min(p, player) + "|" + std::max(p, player), 0);
                            break;
                        }
                    const auto delay =
                        1 + (400 - skill.at("decisions").get<int>() - skill.at("coordination").get<int>() -
                             skill.at("leadership").get<int>() - chemistry) /
                                55;
                    review = std::min(review, plus_ticks(now, delay));
                }
            }
            a["knowledge"][id] = std::move(sight);
        }
    }
    void deliver_radio(Json &w) const {
        const Tick now = w.at("tick");
        auto &messages = w.at("messages");
        if (std::none_of(messages.begin(), messages.end(), [&](const Json &m) { return m.at("due") <= now; }))
            return;
        auto &roster = w.at("agents");
        // Prepare only affected recipients. A malformed report cannot consume the queue.
        std::map<std::size_t, Json> changes;
        Json pending = Json::array();
        bool live = w.at("phase") == "live" && w.at("plans").contains("CT");
        Tick review = live ? w.at("plans").at("CT").at("review").get<Tick>() : 0;
        for (const auto &m : messages) {
            if (m.at("due") > now) {
                pending.push_back(m);
                continue;
            }
            for (std::size_t i = 0; i < roster.size(); ++i) {
                const auto &a = roster.at(i);
                if (a.at("hp") == 0 || a.at("team") != m.at("team") || a.at("id") == m.at("sender"))
                    continue;
                auto [it, inserted] = changes.try_emplace(i, a);
                deliver(w, it->second, m, now, review);
            }
        }
        if (live)
            w.at("plans").at("CT").at("review") = review;
        for (auto &[i, a] : changes)
            roster.at(i).swap(a);
        messages.swap(pending);
    }
};

MatchState::MatchState(const std::string &checkpoint, std::string current, std::set<std::string> old,
                       std::set<std::string> calls, int freeze, int build, const std::string &rulebook)
    : impl_(std::make_unique<Impl>(checkpoint, std::move(current), old, std::move(calls), freeze, build,
                                   rulebook)) {}
MatchState::~MatchState() = default;
std::string MatchState::snapshot() const {
    std::scoped_lock lock(impl_->mutex);
    return impl_->state.dump();
}
void MatchState::command(const std::string &kind, const std::string &value) {
    std::scoped_lock lock(impl_->mutex);
    // Coach commands are rare and externally retriable. Commit event and state together.
    Json staged = impl_->state;
    impl_->apply_command(staged, kind, value);
    impl_->state.swap(staged);
}
int MatchState::advance_intermission(int ticks) {
    if (ticks < 0)
        throw std::invalid_argument("Отрицательное количество тиков");
    std::scoped_lock lock(impl_->mutex);
    auto &w = impl_->state;
    if (ticks == 0 || (w.at("phase") != "freeze" && w.at("phase") != "result"))
        return 0;
    const Tick tick = w.at("tick"), deadline = w.at("deadline");
    const bool can_start = w.at("phase") == "result" && !impl_->spawns.is_null();
    if (!can_start && (deadline <= tick || deadline - tick <= 1))
        return 0;
    const auto until = deadline > tick ? deadline - tick : 1;
    auto count = std::min<Tick>(ticks, can_start ? until : until - 1);
    // Starting a round archives the old ledger and installs a new one. Publish both atomically.
    const bool transition = can_start && count == until;
    Json staged;
    if (transition)
        staged = w;
    auto &current = transition ? staged : w;
    if (current.at("rules") != impl_->rules) {
        Json transition = {
            {"previous", current.at("rules")}, {"tick", tick}, {"lastEvent", current.at("serial")}};
        current["rulesTransition"] = std::move(transition);
        current.at("rules") = impl_->rules;
    }
    auto &agents = current.at("agents");
    auto key = [&](const Json &a) {
        return std::pair{a.at("teamId") != current.at("firstAttackTeamId"), a.at("slot").get<int>()};
    };
    std::stable_sort(agents.begin(), agents.end(),
                     [&](const auto &a, const auto &b) { return key(a) < key(b); });
    current["started"] = true;
    current.at("tick") = plus_ticks(tick, count);
    if (transition) {
        start_round(current, impl_->config, impl_->spawns);
        if (current.at("pending") == true)
            impl_->enter_timeout(current);
        w.swap(staged);
    }
    return int(count);
}
void MatchState::deliver_radio() {
    std::scoped_lock lock(impl_->mutex);
    impl_->deliver_radio(impl_->state);
}
void MatchState::observe() {
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->combat || !impl_->objectives)
        throw std::invalid_argument("Физика карты недоступна");
    auto staged = impl_->state;
    impl_->deliver_radio(staged);
    observe_contacts(staged, impl_->combat->sensors(), *impl_->objectives);
    impl_->state.swap(staged);
}
void MatchState::finish_round(const std::string &side, const std::string &reason) {
    std::scoped_lock lock(impl_->mutex);
    if (impl_->state.at("phase") == "finished" || impl_->state.at("phase") == "result")
        return;
    Json staged = impl_->state;
    settle_round(staged, impl_->config, side, reason);
    impl_->state.swap(staged);
}

void MatchState::attach_spawns(const std::string &map, const std::string &serialized) {
    auto parsed = Json::parse(serialized);
    for (const auto side : {"T", "CT"}) {
        const auto &rows = parsed.at(side);
        if (!rows.is_array() || rows.size() < 5)
            throw std::invalid_argument("Неполная таблица старта карты");
        for (const auto &row : rows) {
            if (row.size() != 3 || !row.at(2).is_number_integer() || !row.at(1).is_number())
                throw std::invalid_argument("Повреждена позиция старта карты");
            row.at(0).get<Point>();
        }
    }
    std::scoped_lock lock(impl_->mutex);
    if (impl_->state.at("mapId") != map || !impl_->spawns.is_null())
        throw std::invalid_argument("Таблица старта уже задана или принадлежит другой карте");
    impl_->spawns.swap(parsed);
}

void MatchState::attach_physics(const std::string &map, std::shared_ptr<const PhysicalNavigation> planner,
                                std::vector<std::string> materials) {
    std::scoped_lock lock(impl_->mutex);
    if (impl_->state.at("mapId") != map || impl_->combat)
        throw std::invalid_argument("Неожиданная физическая карта");
    impl_->combat = std::make_unique<Combat>(std::move(planner), std::move(materials));
}
void MatchState::resolve_actions(const std::string &input) {
    auto intents = Json::parse(input);
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->combat)
        throw std::invalid_argument("Физика карты недоступна");
    if (impl_->state.at("phase") != "live" && impl_->state.at("phase") != "planted")
        throw std::invalid_argument("Действия требуют активной фазы раунда");
    auto staged = impl_->state;
    impl_->combat->execute(staged, impl_->config, intents);
    impl_->state.swap(staged);
}

void MatchState::apply_effects() {
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->combat)
        throw std::invalid_argument("Физика карты недоступна");
    if (impl_->state.at("phase") != "live" && impl_->state.at("phase") != "planted")
        throw std::invalid_argument("Эффекты требуют активной фазы раунда");
    auto staged = impl_->state;
    impl_->combat->effects(staged, impl_->config);
    impl_->state.swap(staged);
}

void MatchState::attach_objectives(const std::string &map, std::shared_ptr<const Objectives> sites) {
    std::scoped_lock lock(impl_->mutex);
    if (!sites || impl_->objectives || impl_->state.at("mapId") != map)
        throw std::invalid_argument("Неожиданная карта плентов");
    impl_->objectives = std::move(sites);
}
void MatchState::resolve_intents(const std::string &input) {
    auto intents = Json::parse(input);
    if (!intents.is_array())
        throw std::invalid_argument("Expected an intent batch");
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->combat || !impl_->objectives)
        throw std::invalid_argument("Физика карты недоступна");
    const auto &phase = impl_->state.at("phase");
    if (phase != "live" && phase != "planted")
        throw std::invalid_argument("Требуется активный раунд");
    if (impl_->state.at("tick").get<Tick>() % 2 == 0)
        std::reverse(intents.begin(), intents.end());
    auto staged = impl_->state;
    auto attacks = Json::array();
    for (const auto &intent : intents)
        if (intent.at("kind") == "shoot" || intent.at("kind") == "throw")
            attacks.push_back(intent);
    impl_->combat->execute(staged, impl_->config, attacks);
    impl_->objectives->resolve(staged, impl_->config, intents);
    impl_->state.swap(staged);
}

std::string MatchState::board_step(const std::string &id, const std::string &device,
                                   const std::vector<Hazard> &fire) {
    auto bomb = Json::parse(device);
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->objectives)
        throw std::invalid_argument("Физика карты недоступна");
    auto staged = impl_->state;
    for (auto &a : staged.at("agents"))
        if (a.at("id") == id) {
            auto result = esport::board_step(staged, a, impl_->config, *impl_->objectives, bomb, fire).dump();
            impl_->state.swap(staged);
            return result;
        }
    throw std::invalid_argument("Игрок отсутствует в матче");
}

void MatchState::assign_board(const std::string &input) {
    const auto board = Json::parse(input);
    std::scoped_lock lock(impl_->mutex);
    impl_->authorize(impl_->state);
    auto w = impl_->state;
    if (board.at("map") != w.value("mapId", std::string("depo")) ||
        board.at("geometry") != w.at("map_version"))
        throw std::invalid_argument("Тактика создана для другой карты или версии геометрии");
    const std::string side = board.at("side"), buy = board.at("buy");
    const auto coach = team_side(w.at("agents"), w.at("coachTeamId"));
    if (w.at("phase") == "timeout") {
        Json scenario;
        if (w.contains("nextBoard") && !w.at("nextBoard").empty() && w.at("nextBoard").at("buy") == "Эко")
            scenario = "Эко";
        else {
            const auto call =
                w.contains("nextBoard") && !w.at("nextBoard").empty() ? Json(nullptr) : w.at("call");
            scenario =
                esport::buy_decision(w, impl_->config, coach, call, nullptr, nullptr, nullptr).at("scenario");
        }
        if (coach != side ||
            (scenario != buy && !(scenario != "Эко" && scenario != "Пистолетная" && buy == "Оружейная")))
            throw std::invalid_argument("Тактика не соответствует стороне или закупке ближайшего раунда");
        w["nextBoard"] = board;
        w["call"] = board.at("name");
    } else if (w.at("round") == 1 && w.at("tick") == 0 && w.at("phase") == "freeze" &&
               !w.value("started", false) &&
               w.at("remaining") == w.value("openingTimeouts", impl_->config.at("rules").at("timeouts"))) {
        w["playbook"][side + "/" + buy] = board;
    } else
        throw std::invalid_argument("Назначение возможно до старта матча или в свой тактический тайм-аут");
    Json ref = Json::object();
    for (auto k : {"id", "revision", "name", "side", "buy"})
        ref[k] = board.at(k);
    emit(w, "board_call",
         "Назначена тактика «" + board.at("name").get<std::string>() + "» · в" + board.at("revision").dump(),
         coach)["tactic"] = std::move(ref);
    impl_->state.swap(w);
}

std::string MatchState::buy_decision(const std::string &side, const std::string &options) const {
    auto input = Json::parse(options);
    std::scoped_lock lock(impl_->mutex);
    return esport::buy_decision(impl_->state, impl_->config, side, input.value("call", Json(nullptr)),
                                input.value("site", Json(nullptr)), input.value("board", Json(nullptr)),
                                input.value("requested", Json(nullptr)))
        .dump();
}
void MatchState::buy_equipment(const std::string &side, const std::string &strategy,
                               const std::string &board) {
    Json purchase = Json::parse(strategy), plan = Json::parse(board);
    std::scoped_lock lock(impl_->mutex);
    if (impl_->state.at("phase") != "freeze")
        throw std::invalid_argument("Закупка доступна во время подготовки");
    auto staged = impl_->state;
    esport::buy_equipment(staged, impl_->config, side, purchase, plan);
    impl_->state.swap(staged);
}
} // namespace esport
