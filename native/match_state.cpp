#include "coaching.hpp"
#include "grenades.hpp"
#include "radio.hpp"
#include "match_state.hpp"
#include "agent_turn.hpp"
#include "economy.hpp"
#include "grid_round.hpp"
#include "navigation.hpp"
#include "observation.hpp"
#include "opening.hpp"
#include "round_rules.hpp"
#include "tactic_execution.hpp"
#include "team_ai.hpp"
#include "tick_output.hpp"

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

// During a batch the roster can change arbitrarily. The domain and external
// series metadata are read-only, while completed rounds and events only append.
// Move these large values into the transaction and remember the journal cursor.
class BatchCheckpoint {
    Json &original;
    std::size_t rounds, events;
    bool committed = false;
    static constexpr std::array borrowed{"domain", "series", "archive", "events"};

  public:
    Json world = Json::object();
    explicit BatchCheckpoint(Json &source)
        : original(source), rounds(source.at("archive").size()), events(source.at("events").size()) {
        world.get_ref<Json::object_t &>().reserve(source.size() + 16);
        for (auto &[key, value] : source.items())
            world[key] =
                std::find(borrowed.begin(), borrowed.end(), key) == borrowed.end() ? value : Json(nullptr);
        for (auto key : borrowed)
            if (source.contains(key))
                source.at(key).swap(world.at(key));
    }
    BatchCheckpoint(const BatchCheckpoint &) = delete;
    ~BatchCheckpoint() {
        if (committed)
            return;
        auto &archive = world.at("archive");
        if (archive.size() > rounds) {
            world.at("events").swap(archive.at(rounds));
            archive.erase(archive.begin() + rounds, archive.end());
        }
        auto &journal = world.at("events");
        journal.erase(journal.begin() + events, journal.end());
        for (auto key : borrowed)
            if (original.contains(key))
                original.at(key).swap(world.at(key));
    }
    void commit() {
        original.swap(world);
        committed = true;
    }
};
} // namespace

class MatchState::Impl {
  public:
    Json state, config, spawns;
    std::shared_ptr<const GridMap> grid;
    std::unique_ptr<Combat> combat;
    std::shared_ptr<const Objectives> objectives;
    std::shared_ptr<const OpeningMap> opening;
    const OpeningMap &opening_map() const {
        if (!opening)
            throw std::invalid_argument("Данные плана карты отсутствуют");
        return *opening;
    }
    Json &captain(const std::string &side) {
        for (auto &a : state.at("agents"))
            if (a.at("team") == side && a.at("appointed") == true)
                return a;
        throw std::invalid_argument("Капитан не назначен");
    }
    std::string rules;
    std::set<std::string> calls;
    int freeze;
    mutable std::mutex mutex;
    Impl(const std::string &checkpoint, std::string current_rules, const std::set<std::string> &old_rules,
         std::set<std::string> commands, int freeze_ticks, int build, const std::string &rulebook)
        : state(Json::parse(checkpoint)), config(Json::parse(rulebook)), rules(std::move(current_rules)),
          calls(std::move(commands)), freeze(freeze_ticks) {
        if (!state.contains("mapId") && config.contains("grid") &&
            state.at("map_version") == config.at("grid").at("version") &&
            state.at("checkpointVersion") == 6) {
            auto &spec = config.at("grid");
            rules = spec.at("rules").get<std::string>();
            grid = std::make_shared<GridMap>(spec);
            spawns = spec.at("spawns");
            combat = std::make_unique<Combat>(grid);
            objectives = std::make_shared<Objectives>(grid);
            opening = std::make_shared<OpeningMap>(objectives);
        }
        if (state.contains("agentPolicy") && (!state.at("agentPolicy").is_number_integer() ||
                                              (state.at("agentPolicy") < 1 || state.at("agentPolicy") > 12)))
            throw std::invalid_argument("Неизвестная версия индивидуального ИИ");
        if (spatial_grenades(state) && config.contains("utility")) {
            config.at("utility").at("Дым")[1] = 200;
            config.at("utility").at("Ложная")[1] = 150;
        }
        if (freeze <= 0 ||
            (!grid && (state.at("map_version") != build || state.at("checkpointVersion") != 7)) ||
            !(state.at("rules") == rules ||
              (!grid && old_rules.contains(state.at("rules").get<std::string>()))))
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
        if (w.contains("talkSeconds")) {
            w["breakOwner"] = coach;
            w.at("talkSeconds") = break_seconds(w, config.at("rules"));
            timeout_recovery(w, coach);
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
        if (w.value("autonomous",false) || (w.contains("series") && w.at("series").value("spectator",false)) ||
            (w.contains("breakOwner") && w.at("phase") != "timeout"))
            throw std::invalid_argument("Идёт перерыв другой команды");
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
        else if (kind == "address" && w.contains("talkSeconds"))
            coach_address(w, coach, Json::parse(value));
        else if (kind == "call" && calls.contains(value)) {
            if (w.at("call") != value || w.contains("nextBoard")) spend_talk_time(w,10);
            w.erase("nextBoard");
            w["call"] = value;
            emit(w, "call", "Указание на следующий раунд · " + value, team_side(w.at("agents"), coach));
        } else if (kind == "resume") {
            w.erase("breakOwner");
            w["phase"] = "freeze";
            w["deadline"] = plus_ticks(w.at("tick"), freeze);
            emit(w, "resume", "Тайм-аут завершён");
        } else
            throw std::invalid_argument("Неизвестное указание");
    }

    void deliver(const Json &w, Json &a, const Json &m, Tick now, Tick &review, int quality) const {
        const auto sender = m.at("sender").get<std::string>();
        if (m.contains("feedback") && quality >= 0) {
            Json call = m.at("feedback");
            const Tick observed = call.at("tick");
            if (observed > now || now - observed >= 30)
                return;
            if (group_tasks(w) && call.contains("members") && has_value(call.at("members")) &&
                std::find(call.at("members").begin(), call.at("members").end(), a.at("id")) != call.at("members").end())
                a["groupInboxTick"] = now;
            auto &previous = a["peerCalls"][sender + "/" + call.at("channel").get<std::string>()];
            if (previous.is_null() || previous.at("tick") < observed ||
                (previous.at("tick") == observed && call.value("sequence", 0) > previous.value("sequence", 0))) {
                call["sender"] = sender;
                call["quality"] = quality;
                previous = std::move(call);
            }
        } else if (m.contains("crossing")) {
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
        } else if (m.contains("flashWarning")) {
            receive_flash_warning(a, m.at("flashWarning"), sender, coordinated_utility(w));
        } else if (m.contains("friendlyUtility")) {
            const auto &cue = m.at("friendlyUtility");
            if (cue.contains("cast")) {
                const auto &cast = cue.at("cast");
                if (cue.contains("openingCall"))
                    a[cue.at("openingCall") == "flash" ? "pushFlash" : "openingThrows"][cue.at("site").get<std::string>()] = sender;
                if (spatial_grenades(w) && cast.at("item") == "Свет" && !coordinated_utility(w) &&
                    !a.contains("flashWarning"))
                    a["flashWarning"] = nullptr;
                auto &calls = a["crossingCalls"];
                if (calls.is_null())
                    calls = Json::array();
                calls.erase(std::remove_if(calls.begin(), calls.end(), [&](const Json &c) {
                    return c.at("end") <= now;
                }), calls.end());
                if (spatial_grenades(w) && cast.at("item") == "Свет" && cast.contains("land") &&
                    now < cast.at("land"))
                    receive_flash_warning(a,
                                          {{"point", cast.at("point")},
                                           {"land", cast.at("land")},
                                           {"ticket", cast.value("ticket", Json(nullptr))}},
                                          sender, coordinated_utility(w));
                if (cast.at("end") > now)
                    calls.push_back(cast);
                if (cast.at("item") != "Дым" && cast.at("item") != "Огонь")
                    return;
            }
            auto items = a.value("friendlyUtility", Json::array());
            items.erase(
                std::remove_if(items.begin(), items.end(), [&](const Json &p) { return p.at("end") < now; }),
                items.end());
            items.push_back(m.at("friendlyUtility"));
            a["friendlyUtility"] = std::move(items);
        } else if (m.contains("blockedSite")) {
            auto &reports = a.at("routeReports");
            auto observed = m.value("observed", now);
            if (observed <= now && (!reports.contains(sender) || reports.at(sender).at(1) <= observed))
                reports[sender] = Json::array({m.at("blockedSite"), observed});
        } else if (m.contains("device")) {
            a["seenDevice"] = m.at("device");
            a["heardSite"] = m.at("device").at("site");
        } else if (m.contains("site"))
            a["heardSite"] = m.at("site");
        else {
            auto sight = m.at("sight");
            auto id = sight.at("id").get<std::string>();
            auto &knowledge = a.at("knowledge");
            Json *old = knowledge.contains(id) ? &knowledge.at(id) : nullptr;
            if (quality >= 0) {
                if (!accept_report(sight, old, sender, quality, now))
                    return;
            } else if (sight.at("tick") <= (old ? old->value("tick", Tick{-1}) : -1))
                return;
            if (sight.at("source") != "Граната" && sight.at("source") != "Слух")
                sight["source"] = "Радио";
            if (!grid && (a.at("team") == "CT" || w.value("agentPolicy",0)>=12) && w.at("phase") == "live") {
                sight["reporter"] = sender;
                if (a.at("id") == w.at("plans").at(a.at("team").get<std::string>()).at("captain") &&
                    sight.at("source") == "Радио" &&
                    (!old ||
                     (sight.contains("entrySite") &&
                      sight.at("entrySite") != old->value("entrySite", Json(nullptr))) ||
                     (sight.value("carryingC4", false) && !old->value("carryingC4", false)) ||
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
        // The batch owns rollback, including all previously delivered reports.
        Json pending = Json::array();
        bool live = w.at("phase") == "live" && w.at("plans").contains("CT");
        Tick review = live ? w.at("plans").at("CT").at("review").get<Tick>() : 0;
        Tick attack_review = live ? w.at("plans").at("T").at("review").get<Tick>() : 0;
        for (const auto &m : messages) {
            if (m.at("due") > now) {
                pending.push_back(m);
                continue;
            }
            const Json *speaker = nullptr;
            if (peer_radio(w) && (m.contains("sight") || m.contains("feedback"))) {
                auto found = std::find_if(roster.begin(), roster.end(), [&](const Json &p) {
                    return p.at("id") == m.at("sender") && p.at("team") == m.at("team");
                });
                if (found == roster.end())
                    throw std::invalid_argument("Неизвестный отправитель радио");
                speaker = &*found;
            }
            for (std::size_t i = 0; i < roster.size(); ++i) {
                auto &a = roster.at(i);
                if (a.at("hp") == 0 || a.at("team") != m.at("team") || a.at("id") == m.at("sender"))
                    continue;
                deliver(w, a, m, now, a.at("team")=="T" ? attack_review : review, speaker ? reception_quality(w, *speaker, a) : -1);
            }
        }
        if (live)
            w.at("plans").at("CT").at("review") = review;
        if (live && w.value("agentPolicy",0)>=12) w.at("plans").at("T").at("review")=attack_review;
        messages.swap(pending);
    }
    void resolve(Json &world, Json &intents) const {
        if (world.at("tick").get<Tick>() % 2 == 0)
            std::reverse(intents.begin(), intents.end());
        auto attacks = Json::array();
        for (const auto &intent : intents)
            if (intent.at("kind") == "shoot" || intent.at("kind") == "throw")
                attacks.push_back(intent);
        combat->execute(world, config, attacks);
        objectives->resolve(world, config, intents);
    }
    int advance(int ticks, TickSamples *output);
    void tick(Json &world, TickSamples *output) const {
        auto &roster = world.at("agents");
        world.at("tick") = plus_ticks(world.at("tick"), 1);
        const Tick now = world.at("tick");
        if (world.at("phase") == "freeze" || world.at("phase") == "result") {
            finish_ai_break(world, now);
            if (now >= world.at("deadline")) {
                if (world.at("phase") == "result") {
                    start_round(world, config, spawns);
                    if (world.at("pending") == true)
                        enter_timeout(world);
                    else
                        consider_break(world, config.at("rules"));
                } else
                    opening_map().begin_live(world, config);
            }
            return;
        }
        combat->effects(world, config);
        // The burst samples the turned head. Reacquire the previous angle
        // before the next observation.
        if (coordinated_utility(world))
            for (auto &actor : roster) {
                auto look = actor.find("resumeFlashLook");
                if (look != actor.end() && now >= look->at("land")) {
                    actor["heading"] = look->at("heading");
                    actor.erase(look);
                }
            }
        deliver_radio(world);
        if (grid)
            grid_observe(world, *grid);
        else
            observe_contacts(world, combat->sensors(), *objectives);
        auto &traces = world.at("traces");
        traces.erase(
            std::remove_if(traces.begin(), traces.end(),
                           [&](const Json &trace) { return now - trace.at("tick").get<Tick>() >= 45; }),
            traces.end());
        Json intents = Json::array();
        for (std::string side : {"T", "CT"}) {
            Squad squad;
            for (auto &a : roster)
                if (a.at("team") == side && a.at("hp") != 0)
                    squad.push_back(&a);
            if (squad.empty())
                continue;
            if (grid)
                grid_review(world, squad, *grid);
            else
                captain_review(world, config, opening_map(), side);
            Json recovery = !grid && side == "T" ? rescue_c4(world, objectives->map(), squad) : Json(nullptr);
            for (auto actor : squad) {
                AgentTurn turn(world, *actor, squad, config, opening_map(), *combat, recovery);
                Json goal;
                if (output && output->traces_actions(now))
                    turn.requested_goal = &goal;
                turn.prepare();
                auto intent = turn.priority_intent();
                if (intent.is_null())
                    intent = turn.spatial_intent();
                intent = turn.prepare_flash(std::move(intent));
                turn.finish(intent);
                if (turn.requested_goal)
                    output->actions[actor->at("id").get<std::string>()] = {intent.at(0), std::move(goal)};
                intents.push_back(
                    Json{{"actor", actor->at("id")}, {"kind", intent[0]}, {"target", std::move(intent[1])}});
            }
        }
        resolve(world, intents);
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
int MatchState::Impl::advance(int ticks, TickSamples *output) {
    if (ticks < 0)
        throw std::invalid_argument("Отрицательное количество тиков");
    const auto &initial = state;
    if (!ticks || initial.at("phase") == "finished" || initial.at("phase") == "timeout")
        return 0;
    if (!combat || !opening || !objectives || spawns.is_null())
        throw std::invalid_argument("Данные карты отсутствуют");
    // Publish the entire requested batch atomically, including the journal and RNG.
    BatchCheckpoint batch(state);
    auto &staged = batch.world;
    if (staged.at("rules") != rules) {
        staged["rulesTransition"] = Json{{"previous", staged.at("rules")},
                                         {"tick", staged.at("tick")},
                                         {"lastEvent", staged.at("serial")}};
        staged.at("rules") = rules;
    }
    auto &roster = staged.at("agents");
    auto rank = [&](const Json &a) {
        return std::pair{a.at("teamId") != staged.at("firstAttackTeamId"), a.at("slot").get<int>()};
    };
    std::stable_sort(roster.begin(), roster.end(), [&](auto &l, auto &r) { return rank(l) < rank(r); });
    staged["started"] = true;
    int count = 0;
    while (count < ticks && staged.at("phase") != "finished" && staged.at("phase") != "timeout" &&
           (!output || !output->end_of_preview(staged))) {
        if (output)
            output->before(staged);
        tick(staged, output);
        if (output)
            output->after(staged, opening.get());
        ++count;
    }
    batch.commit();
    return count;
}
int MatchState::advance(int ticks) {
    std::scoped_lock lock(impl_->mutex);
    return impl_->advance(ticks, nullptr);
}
std::string MatchState::advance_recorded(int ticks, TickOutput mode) {
    std::scoped_lock lock(impl_->mutex);
    TickSamples samples(mode);
    impl_->advance(ticks, &samples);
    return samples.finish(impl_->state).dump();
}
int MatchState::advance_intermission(int ticks) {
    if (ticks < 0)
        throw std::invalid_argument("Отрицательное количество тиков");
    std::scoped_lock lock(impl_->mutex);
    auto &w = impl_->state;
    if (ticks == 0 || (w.at("phase") != "freeze" && w.at("phase") != "result"))
        return 0;
    const Tick tick = w.at("tick"), deadline = w.at("deadline");
    const bool can_start = (w.at("phase") == "result" && !impl_->spawns.is_null()) ||
                           (w.at("phase") == "freeze" && impl_->opening);
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
    finish_ai_break(current,current.at("tick"));
    if (transition) {
        if (current.at("phase") == "result") {
            start_round(current, impl_->config, impl_->spawns);
            if (current.at("pending") == true)
                impl_->enter_timeout(current);
            else
                consider_break(current, impl_->config.at("rules"));
        } else {
            impl_->opening_map().begin_live(current, impl_->config);
        }
        w.swap(staged);
    }
    return int(count);
}
void MatchState::begin_live() {
    std::scoped_lock lock(impl_->mutex);
    if (impl_->state.at("phase") != "freeze")
        throw std::invalid_argument("Требуется подготовка раунда");
    auto staged = impl_->state;
    impl_->opening_map().begin_live(staged, impl_->config);
    impl_->state.swap(staged);
}
void MatchState::deliver_radio() {
    std::scoped_lock lock(impl_->mutex);
    BatchCheckpoint batch(impl_->state);
    impl_->deliver_radio(batch.world);
    batch.commit();
}
std::string MatchState::priority_intent(const std::string &id, const std::string &input) {
    auto observation = Json::parse(input);
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->combat)
        throw std::invalid_argument("Физика карты недоступна");
    auto staged = impl_->state;
    auto &roster = staged.at("agents");
    auto agent = std::find_if(roster.begin(), roster.end(),
                              [&](const Json &a) { return a.at("id") == id && a.at("hp") != 0; });
    if (agent == roster.end())
        throw std::invalid_argument("Игрок недоступен");
    Squad squad;
    for (auto &a : roster)
        if (a.at("team") == agent->at("team") && a.at("hp") != 0)
            squad.push_back(&a);
    const auto recovery = observation.value("recovery", Json(nullptr));
    AgentTurn turn(staged, *agent, squad, impl_->config, impl_->opening_map(), *impl_->combat, recovery);
    turn.action = observation.at("action");
    turn.device = observation.at("device");
    for (auto &f : observation.at("fire"))
        turn.fire.emplace_back(actor_point(f), f.at("radius"));
    turn.opening_sight = observation.value("openingSight", false);
    auto result = turn.priority_intent();
    if (result.is_null())
        result = turn.spatial_intent();
    auto encoded = turn.prepare_flash(std::move(result)).dump();
    impl_->state.swap(staged);
    return encoded;
}
void MatchState::review_captain(const std::string &side) {
    if (side != "T" && side != "CT")
        throw std::invalid_argument("Неизвестная сторона");
    std::scoped_lock lock(impl_->mutex);
    auto staged = impl_->state;
    if (impl_->grid) {
        Squad squad;
        for (auto &a : staged.at("agents"))
            if (a.at("team") == side && a.at("hp") != 0)
                squad.push_back(&a);
        if (!squad.empty())
            grid_review(staged, squad, *impl_->grid);
    } else
        captain_review(staged, impl_->config, impl_->opening_map(), side);
    impl_->state.swap(staged);
}
void MatchState::observe() {
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->combat || !impl_->objectives)
        throw std::invalid_argument("Физика карты недоступна");
    auto staged = impl_->state;
    impl_->deliver_radio(staged);
    if (impl_->grid)
        grid_observe(staged, *impl_->grid);
    else
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
    auto staged = impl_->state;
    impl_->resolve(staged, intents);
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

void MatchState::attach_opening(const std::string &map, std::shared_ptr<const OpeningMap> opening) {
    std::scoped_lock lock(impl_->mutex);
    if (!opening || impl_->state.at("mapId") != map)
        throw std::invalid_argument("Неверная карта");
    impl_->opening = std::move(opening);
}
std::string MatchState::defense_orders(const std::string &site, int lane) const {
    std::scoped_lock lock(impl_->mutex);
    return impl_->opening_map().defense_orders(impl_->state, site, lane).dump();
}
std::string MatchState::attack_orders(const std::string &site, int lane, const std::string &style) const {
    std::scoped_lock lock(impl_->mutex);
    return impl_->opening_map().attack_orders(impl_->state, site, lane, style).dump();
}
std::string MatchState::opening_call(const std::string &side, const std::string &buy, const std::string &site,
                                     const std::string &style, const std::string &coach) {
    auto call = Json::parse(coach);
    std::scoped_lock lock(impl_->mutex);
    auto &original = impl_->captain(side);
    auto captain = original;
    auto result = impl_->opening_map().call(impl_->state, captain, buy, site, style, call).dump();
    original.swap(captain);
    return result;
}
std::string MatchState::select_defense(const std::string &plan, const std::string &predicted,
                                       const std::string &explicit_site) {
    std::scoped_lock lock(impl_->mutex);
    auto &original = impl_->captain("CT");
    auto captain = original;
    auto result = impl_->opening_map()
                      .select_defense(impl_->state, captain, Json::parse(plan), Json::parse(predicted),
                                      Json::parse(explicit_site))
                      .dump();
    original.swap(captain);
    return result;
}
std::string MatchState::defensive_read() const {
    std::scoped_lock lock(impl_->mutex);
    return esport::defensive_read(impl_->state, impl_->captain("CT")).dump();
}
std::string MatchState::default_probe(const std::string &plan) const {
    std::scoped_lock lock(impl_->mutex);
    return impl_->opening_map().default_probe(impl_->state, Json::parse(plan), impl_->config).dump();
}

void MatchState::assign_board(const std::string &input) {
    const auto board = Json::parse(input);
    std::scoped_lock lock(impl_->mutex);
    impl_->authorize(impl_->state);
    auto w = impl_->state;
    if ((w.contains("breakOwner") && w.at("phase") != "timeout") || (w.value("autonomous", false) || (w.contains("series") && w.at("series").value("spectator", false))))
        throw std::invalid_argument("Решения принимает тренер команды");
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
            scenario = impl_->grid
                           ? Json(grid_buy(w, impl_->config, coach, call))
                           : esport::buy_decision(w, impl_->config, coach, call, nullptr, nullptr, nullptr)
                                 .at("scenario");
        }
        if (coach != side ||
            (scenario != buy && !(scenario != "Эко" && scenario != "Пистолетная" && buy == "Оружейная")))
            throw std::invalid_argument("Тактика не соответствует стороне или закупке ближайшего раунда");
        if (!w.contains("nextBoard") || w.at("nextBoard") != board) spend_talk_time(w,15);
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
