#include "combat.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace esport {
namespace {
Point xyz(const Json &j) { return {j.at("x"), j.at("y"), j.at("z")}; }
const Json &skills(const Json &w, const Json &a) {
    return w.at("domain").at("players").at(a.at("playerId").get<std::string>()).at("skills");
}
int draw(Json &a) {
    const auto next = a.at("rng").get<std::uint32_t>() * 1664525u + 1013904223u;
    a.at("rng") = next;
    return int(next >> 16);
}
int accuracy(const Json &w, const Json &cfg, const Json &a, const Json &spec, double gap, int burst) {
    const auto &player = w.at("domain").at("players").at(a.at("playerId").get<std::string>());
    const auto &skill = player.at("skills");
    auto s = [&](const std::string &k) { return skill.at(k).get<double>(); };
    const auto now = w.at("tick").get<Tick>();
    std::string weapon = a.at("weapon");
    double base = spec.at("accuracy").get<double>() + (s("aim") - 65) * .19;
    base -= gap * (weapon == "Nova" ? .95 : .36) * (1.4 - s(cfg.at("classes").at(weapon)) / 140);
    if (burst)
        base -= burst * (8 - s("recoil") * .065);
    else
        base += (s("first_shot") - 65) * .10;
    base -= std::min(3., a.at("observedSpeed").get<double>()) * (100 - s("tracking")) / 16;
    base -= std::max<Tick>(0, 6 - (now - a.at("lastMove").get<Tick>())) * (100 - s("counter_strafe")) / 30;
    base += a.at("dayRoll").get<double>() * (100 - s("consistency")) / 100;
    base += (player.at("form").get<double>() - 50) / 12;
    base -= a.at("pressure").get<double>() * (100 - s("stress_resistance")) / 10;
    base -= std::min(1., (now - a.at("liveStart").get<Tick>()) / 850.) * (100 - s("concentration")) / 12;
    base -= std::max<Tick>(0, 12 - (now - a.at("lastHurt").get<Tick>())) * (100 - s("composure")) / 110;
    return int(std::clamp(std::nearbyint(base), 8., 96.));
}

void add(Json &v, int delta) { v = v.get<int>() + delta; }
void death(Json &w, const Json &cfg, Json &shooter, Json &target, const std::string &weapon, bool head,
           bool enemy) {
    const std::string ident = target.at("id"), killer = shooter.at("id");
    Json assists = Json::array();
    for (const auto &[a, dmg] : target.at("attackers").items())
        if (a != killer && dmg >= 40)
            assists.push_back(a);
    Json traded = nullptr;
    bool opening = enemy;
    auto &kills = w.at("kills");
    for (auto it = kills.rbegin(); it != kills.rend(); ++it) {
        const auto &k = *it;
        if (k.at("enemy") != true)
            continue;
        opening = false;
        if (traded.is_null() && k.at("player") == ident &&
            w.at("tick").get<Tick>() - k.at("tick").get<Tick>() <= 50)
            for (const auto &a : w.at("agents"))
                if (a.at("id") == k.at("target") && a.at("team") == shooter.at("team"))
                    traded = k.at("target");
    }
    auto &event = emit(w, "kill",
                       shooter.at("name").get<std::string>() + "   " + weapon + "   " +
                           target.at("name").get<std::string>());
    event.update(Json{{"player", killer},
                      {"target", ident},
                      {"weapon", weapon},
                      {"head", head},
                      {"assists", assists},
                      {"trade", traded},
                      {"enemy", enemy},
                      {"opening", opening}});
    const auto kill_id = event.at("id").get<Tick>();
    kills.push_back(event);
    Json gun = {{"id", kill_id}, {"x", target.at("x")}, {"y", target.at("y")}, {"z", target.at("z")}};
    const auto &other = target.at("holster");
    const auto &pistols = cfg.at("sidearms");
    if (!other.is_null() && std::find(pistols.begin(), pistols.end(), other.at("weapon")) == pistols.end())
        gun.update(other);
    else
        for (auto key : {"weapon", "ammo", "reserve"})
            gun[key] = target.at(key);
    w.at("groundWeapons").push_back(std::move(gun));
    if (enemy)
        for (auto &mate : w.at("agents"))
            if (mate.at("hp") != 0 && mate.at("team") == target.at("team")) {
                mate["tradeTarget"] = killer;
                mate["tradeUntil"] = plus_ticks(w.at("tick"), 50);
            }
    target.update(Json{{"status", "Выбыл"}, {"visible", Json::array()}, {"path", Json::array()}});
    auto &stats = w.at("stats");
    add(stats.at(ident).at("d"), 1);
    if (enemy) {
        auto &line = stats.at(killer);
        add(line.at("k"), 1);
        add(line.at("hs"), head);
        add(line.at("opening"), opening);
        const auto &guns = cfg.at("weapons");
        pay(w, shooter, guns.contains(weapon) ? guns.at(weapon).at("reward").get<int>() : 300, "Фраг",
            cfg.at("rules").at("cap"));
    }
    for (const auto &assist : assists)
        add(stats.at(assist.get<std::string>()).at("a"), 1);
    if (w.at("bomb").at("carrier") == ident) {
        w.at("bomb").update(
            Json{{"carrier", nullptr}, {"x", target.at("x")}, {"y", target.at("y")}, {"z", target.at("z")}});
        emit(w, "drop", target.at("name").get<std::string>() + " потерял C4", "T")
            .update(Json{{"x", target.at("x")}, {"y", target.at("y")}});
    }
    target["evidence"] = Json{{"id", kill_id},
                              {"round", w.at("round")},
                              {"text", "Я выбыл в раунде " + std::to_string(w.at("round").get<int>()) +
                                           ". В следующий раз мне нужна поддержка."}};
}
} // namespace

void apply_impact(Json &w, const Json &cfg, Json &shooter, Json &victim, double base,
                  const std::string &weapon, const std::string &group) {
    const auto &guns = cfg.at("weapons");
    bool head = group == "head", enemy = shooter.at("team") != victim.at("team");
    double raw = base;
    if (head && guns.contains(weapon))
        raw *= guns.at(weapon).at("head_multiplier").get<double>();
    else if (group == "stomach")
        raw *= 1.25;
    else if (group == "leg")
        raw *= .75;
    if (victim.at("hp") == 0 || raw <= 0)
        return;
    int armor = victim.at("armor");
    const bool protected_group = group == "chest" || group == "arm" || group == "stomach" ||
                                 group == "blast" || (head && victim.at("helmet") == true);
    int loss = 0;
    if (armor && protected_group) {
        double ratio = guns.contains(weapon) ? guns.at(weapon).at("penetration").get<double>() : .5;
        double absorbed = std::min(raw * (1 - ratio), 2. * armor);
        if (absorbed)
            loss = int(std::clamp(std::nearbyint(absorbed * .5), 1., double(armor)));
        raw -= absorbed;
    }
    victim["armor"] = armor - loss;
    if (armor == loss)
        victim["helmet"] = false;
    int hp = victim.at("hp");
    const int amount = int(std::clamp(raw, 1., double(hp)));
    auto &event = emit(w, "damage",
                       shooter.at("name").get<std::string>() + " → " + victim.at("name").get<std::string>() +
                           " · " + std::to_string(amount) + " HP",
                       shooter.at("team"));
    event.update(Json{{"player", shooter.at("id")},
                      {"target", victim.at("id")},
                      {"amount", amount},
                      {"weapon", weapon},
                      {"head", head},
                      {"hitgroup", group},
                      {"armorLoss", loss}});
    victim["lastHurt"] = w.at("tick");
    victim["hp"] = hp - amount;
    if (enemy) {
        const std::string id = shooter.at("id");
        add(w.at("stats").at(id).at("damage"), amount);
        auto &hits = victim.at("attackers");
        hits[id] = hits.value(id, 0) + amount;
    }
    if (victim.at("hp") == 0)
        death(w, cfg, shooter, victim, weapon, head, enemy);
}

Combat::Combat(std::shared_ptr<const PhysicalNavigation> planner, std::vector<std::string> materials)
    : planner_(std::move(planner)), sensors_(planner_, std::move(materials)) {}

void Combat::shoot(Json &w, const Json &cfg, Json &agent, const Json &sight, Json *victim) const {
    const std::string weapon = agent.at("weapon");
    const auto &spec = cfg.at("weapons").at(weapon);
    Tick now = w.at("tick");
    int burst =
        now - agent.at("lastShot").get<Tick>() > 4 ? 0 : std::min(4, agent.at("burst").get<int>() + 1);
    const auto start = xyz(agent), end = xyz(sight);
    double gap = distance(start, end);
    int chance = accuracy(w, cfg, agent, spec, gap, burst);
    add(agent.at("ammo"), -1);
    agent["lastShot"] = now;
    agent["burst"] = burst;
    agent["ready"] = plus_ticks(
        now, spec.at("interval").get<int>() +
                 (burst >= 3 ? 1 + (100 - skills(w, agent).at("burst_control").get<int>()) / 13 : 0));
    auto &e = emit(w, "shot", agent.at("name").get<std::string>() + " · " + weapon, agent.at("team"));
    e.update(Json{{"player", agent.at("id")},
                  {"target", sight.value("id", Json(nullptr))},
                  {"x", agent.at("x")},
                  {"y", agent.at("y")},
                  {"tx", sight.at("x")},
                  {"ty", sight.at("y")},
                  {"z", agent.at("z")},
                  {"tz", sight.at("z")},
                  {"accuracy", chance},
                  {"burst", burst}});
    w.at("traces").push_back(e);
    bool intersects = victim && victim->at("hp") != 0 && near_segment(start, end, xyz(*victim), 3);
    double transmission =
        intersects ? sensors_.shot_transmission(start, xyz(*victim), spec.at("penetration")) : 1.;
    if (!transmission)
        return;
    for (int i = 0; i < spec.at("pellets").get<int>(); ++i) {
        if (draw(agent) % 100 >= chance || !intersects || victim->at("hp") == 0)
            continue;
        auto location = draw(agent) % 100;
        auto group = location < 24   ? "head"
                     : location < 62 ? "chest"
                     : location < 78 ? "stomach"
                     : location < 89 ? "arm"
                                     : "leg";
        apply_impact(w, cfg, agent, *victim,
                     transmission * spec.at("damage").get<double>() *
                         std::pow(spec.at("falloff").get<double>(), gap / 100),
                     weapon, group);
    }
}
void Combat::throw_grenade(Json &w, const Json &cfg, Json &agent, const Json &target) const {
    const auto &inv = agent.at("utility");
    std::string type = target.contains("utility") && target.at("utility").is_string()
                           ? target.at("utility").get<std::string>()
                           : inv.at(0).get<std::string>();
    auto &items = agent.at("utility");
    auto it = std::find(items.begin(), items.end(), type);
    if (it == items.end())
        throw std::invalid_argument("Граната отсутствует в инвентаре");
    items.erase(it);
    const auto now = w.at("tick").get<Tick>();
    const auto &params = cfg.at("utility").at(type);
    const auto pos = xyz(agent), goal = xyz(target);
    const double rounded = std::nearbyint(distance(pos, goal) / 7);
    if (!(rounded <= std::numeric_limits<int>::max()))
        throw std::invalid_argument("Недопустимая дальность игрового броска");
    const int flight = std::max(3, int(rounded)),
              mastery = skills(w, agent).at(cfg.at("grenadeSkills").at(type).get<std::string>());
    const auto roll = draw(agent);
    const double error = std::min(1., ((100 - mastery) / 100.) * ((roll % 17) / 100.));
    Point aim{std::nearbyint(goal[0] + (pos[0] - goal[0]) * error),
              std::nearbyint(goal[1] + (pos[1] - goal[1]) * error), goal[2]};
    auto track = planner_->grenade(pos, aim, flight);
    const auto landing = track.back();
    Json effect = {{"kind", type},
                   {"player", agent.at("id")},
                   {"team", agent.at("team")},
                   {"x", landing[0]},
                   {"y", landing[1]},
                   {"sx", agent.at("x")},
                   {"sy", agent.at("y")},
                   {"start", now},
                   {"land", plus_ticks(now, flight)},
                   {"end", plus_ticks(plus_ticks(now, flight), params.at(1))},
                   {"radius", params.at(0)},
                   {"z", landing[2]},
                   {"sz", agent.at("z")},
                   {"trajectory", track}};
    if (type == "Дым" || type == "Огонь") {
        Json cue = {{"x", target.at("x")},
                    {"y", target.at("y")},
                    {"z", target.at("z")},
                    {"end", plus_ticks(effect.at("land"), 10)}};
        w.at("messages")
            .push_back(Json{
                {"team", agent.at("team")},
                {"sender", agent.at("id")},
                {"friendlyUtility", cue},
                {"due", plus_ticks(now, 1 + (100 - skills(w, agent).at("communication").get<int>()) / 12)}});
    }
    if (target.contains("openingZone") && !target.at("openingZone").is_null() &&
        target.at("openingZone") != "") {
        auto &job = w.at("plans").at("CT").at("opening").at("jobs").at(agent.at("id").get<std::string>());
        job.at("throw")["land"] = effect.at("land");
        effect["openingZone"] = job.at("zone");
        effect["supported"] = job.at("throw").at("forPlayer");
    }
    w.at("effects").push_back(effect);
    w.at("recentEffects").push_back(effect);
    auto &event = emit(w, "throw", agent.at("name").get<std::string>() + " · " + type, agent.at("team"));
    for (const auto &[key, v] : effect.items())
        if (key != "kind" && key != "team")
            event[key] = v;
    event["utility"] = type;
    if (target.contains("purpose") && !target.at("purpose").is_null() && target.at("purpose") != "")
        event["purpose"] = target.at("purpose");
    agent["throwAt"] = plus_ticks(now, 45);
    agent["ready"] = plus_ticks(now, cfg.at("throwRecovery"));
    agent["status"] = "Бросает гранату";
}

void Combat::execute(Json &w, const Json &cfg, const Json &intents) const {
    // The decision phase supplies actor and aim. Only this stage has authority
    // to look up the current position/HP of the possible collision recipient.
    if (!intents.is_array())
        throw std::invalid_argument("Expected an action batch");
    auto &agents = w.at("agents");
    auto find = [&](const Json &id) -> Json * {
        for (auto &a : agents)
            if (a.at("id") == id)
                return &a;
        return nullptr;
    };
    for (const auto &intent : intents) {
        Json *actor = find(intent.at("actor"));
        if (!actor)
            throw std::invalid_argument("Неизвестный игрок");
        if (actor->at("hp") == 0)
            continue;
        const auto &target = intent.at("target");
        if (intent.at("kind") == "throw")
            throw_grenade(w, cfg, *actor, target);
        else if (intent.at("kind") == "shoot") {
            Json *victim = nullptr;
            if (target.contains("id"))
                victim = find(target.at("id"));
            else {
                double closest = std::numeric_limits<double>::infinity();
                for (auto &a : agents)
                    if (&a != actor && a.at("hp") != 0 && near_segment(xyz(*actor), xyz(target), xyz(a), 3)) {
                        double d = distance(xyz(*actor), xyz(a));
                        if (d < closest) {
                            closest = d;
                            victim = &a;
                        }
                    }
            }
            shoot(w, cfg, *actor, target, victim);
            report_shot(w, *actor, target);
        } else
            throw std::invalid_argument("Неизвестное игровое действие");
    }
}
} // namespace esport

namespace esport {
namespace {
int radio_delay(const Json &w, const Json &a) {
    return 1 + (100 - skills(w, a).at("communication").get<int>()) / 12;
}
Json at(const Point &p) { return Json{{"x", p[0]}, {"y", p[1]}, {"z", p[2]}}; }
bool contains_value(const Json &list, const Json &value) {
    return std::find(list.begin(), list.end(), value) != list.end();
}
} // namespace
Json Combat::sound_position(const Point &p) const {
    if (auto center = planner_->nav_center(p))
        return at(*center);
    Json position = Json::object();
    int i = 0;
    for (auto key : {"x", "y", "z"})
        position[key] = static_cast<std::int64_t>(std::nearbyint(p[i++] / 8)) * 8;
    return position;
}
void Combat::hear(Json &w, const Json &source, const std::string &kind, double radius) const {
    Tick now = w.at("tick");
    auto &roster = w.at("agents");
    std::vector<Listener> listeners;
    const auto ident = source.value("id", Json(nullptr));
    for (const auto &a : roster) {
        bool eligible = a.at("hp") != 0 && a.at("team") == "CT" && !contains_value(a.at("visible"), ident);
        listeners.push_back(
            {xyz(a), eligible ? skills(w, a).at("game_reading").get<double>() : 0., eligible});
    }
    const std::string key = "Шум · " + kind;
    for (const auto &heard : sensors_.hear(xyz(source), radius, listeners)) {
        auto &a = roster.at(heard.listener);
        auto &knowledge = a.at("knowledge");
        bool repeated = false;
        if (knowledge.contains(key)) {
            const auto &prior = knowledge.at(key);
            auto age = now - prior.at("tick").get<Tick>();
            repeated = prior.value("witness", Json(nullptr)) == a.at("id") && age > 0 && age < 18 &&
                       distance(xyz(prior), heard.estimate) < 28;
        }
        Json cue = {{"id", key},
                    {"x", heard.estimate[0]},
                    {"y", heard.estimate[1]},
                    {"z", a.at("z")},
                    {"source", "Слух"},
                    {"tick", now},
                    {"sound", kind},
                    {"witness", a.at("id")},
                    {"repeated", repeated},
                    {"confidence", round_decimal(heard.confidence,2)}};
        knowledge[key] = cue;
        if (!a.contains("audioCalls"))
            a["audioCalls"] = Json::object();
        auto &calls = a.at("audioCalls");
        if (now >= calls.value(kind, Tick{0})) {
            int delay = radio_delay(w, a);
            calls[kind] = plus_ticks(now, 12 + delay);
            w.at("messages")
                .push_back(Json{
                    {"team", "CT"}, {"sender", a.at("id")}, {"sight", cue}, {"due", plus_ticks(now, delay)}});
        }
    }
}
void Combat::report_shot(Json &w, const Json &actor, const Json &target) const {
    Tick now = w.at("tick");
    bool live = w.at("phase") == "live";
    if (actor.at("team") == "T" && live) {
        const auto &gun = actor.at("weapon");
        hear(w, actor, "Выстрел", (gun == "USP" || gun == "M4A1-S") ? 75 : 128);
    }
    for (auto &a : w.at("agents")) {
        if (a.at("hp") == 0 || &a == &actor || contains_value(a.at("visible"), actor.at("id")))
            continue;
        if (near_segment(xyz(actor), xyz(target), xyz(a), 6) &&
            !planner_->hit(xyz(actor), xyz(a), 4, 56, 56)) {
            auto [dx, dy] = sound_direction(xyz(a), xyz(actor));
            a["incoming"] = Json{{"tick", now}, {"bearing", Json::array({a.at("x"), a.at("y"), dx, dy})}};
            if (now >= a.value("nextPressureCall", Tick{0})) {
                int delay = radio_delay(w, a);
                Json pressure = a.at("incoming");
                pressure["origin"] = Json::array({a.at("x"), a.at("y"), a.at("z")});
                a["squadPressure"][a.at("id").get<std::string>()] = pressure;
                a["nextPressureCall"] = plus_ticks(now, 10 + delay);
                w.at("messages")
                    .push_back(Json{{"team", a.at("team")},
                                    {"sender", a.at("id")},
                                    {"pressure", pressure},
                                    {"due", plus_ticks(now, delay)}});
            }
        }
        if (a.at("team") != actor.at("team") && !(live && a.at("team") == "CT") &&
            distance(xyz(a), xyz(actor)) < 55) {
            Json cue = {{"id", "Шум"}};
            cue.update(sound_position(xyz(actor)));
            cue["tick"] = now;
            cue["source"] = "Слух";
            a.at("knowledge")["Шум"] = cue;
            if (now >= a.value("nextSoundCall", Tick{0})) {
                int delay = radio_delay(w, a);
                a["nextSoundCall"] = plus_ticks(now, 10 + delay);
                w.at("messages")
                    .push_back(Json{{"team", a.at("team")},
                                    {"sender", a.at("id")},
                                    {"sight", cue},
                                    {"due", plus_ticks(now, delay)}});
            }
        }
    }
}
} // namespace esport

namespace esport {
void Combat::effects(Json &w, const Json &cfg) const {
    Tick now = w.at("tick");
    auto drop_expired = [&](const char *key, int grace) {
        auto &effects = w.at(key);
        effects.erase(std::remove_if(effects.begin(), effects.end(),
                                     [&](const Json &f) { return f.at("end").get<Tick>() <= now - grace; }),
                      effects.end());
    };
    drop_expired("recentEffects", 42);
    drop_expired("effects", 0);
    auto &roster = w.at("agents");
    for (const auto &f : w.at("effects")) {
        auto p = xyz(f);
        const std::string kind = f.at("kind");
        Tick age = now - f.at("land").get<Tick>();
        double radius = f.at("radius");
        bool decoy = kind == "Ложная", fire = kind == "Огонь";
        if (f.at("team") == "T" && w.at("phase") == "live" &&
            (age == 0 || (decoy && age > 0 && age % 10 == 0)))
            hear(w, f, decoy ? "Выстрел" : "Граната", decoy || kind == "HE" || kind == "Свет" ? 108 : 54);
        if ((kind == "Дым" || fire) && age == 0)
            for (auto &a : roster) {
                if (a.at("hp") == 0 || a.at("id") == f.at("player") || a.at("blind") > now ||
                    distance(xyz(a), p) >= 58)
                    continue;
                auto pos = xyz(a);
                double x = p[0] - pos[0], y = p[1] - pos[1], heading = a.at("heading"),
                       dot = x * std::cos(heading) + y * std::sin(heading);
                if (dot < 0 || 4 * dot * dot < x * x + y * y || planner_->hit(pos, p, 1, 64, 5))
                    continue;
                if (a.contains("friendlyUtility") &&
                    std::ranges::any_of(a.at("friendlyUtility"), [&](const Json &call) {
                        return call.at("end") >= now && distance(xyz(call), p) < 10;
                    }))
                    continue;
                Json cue = {{"id", "Граната"}};
                cue.update(sound_position(p));
                cue["tick"] = now;
                cue["source"] = "Граната";
                a.at("knowledge")["Граната"] = cue;
                w.at("messages")
                    .push_back(Json{{"team", a.at("team")},
                                    {"sender", a.at("id")},
                                    {"sight", cue},
                                    {"due", plus_ticks(now, radio_delay(w, a))}});
            }
        if (age < 0 || kind == "Дым")
            continue;
        if (decoy) {
            if (age % 10 == 0) {
                auto sector = sound_position(p);
                for (auto &a : roster)
                    if (a.at("hp") != 0 && a.at("team") != f.at("team") &&
                        !(a.at("team") == "CT" && w.at("phase") == "live") && distance(xyz(a), p) < radius) {
                        Json cue = {{"id", "Шум"}};
                        cue.update(sector);
                        cue["tick"] = now;
                        cue["source"] = "Слух";
                        a.at("knowledge")["Шум"] = std::move(cue);
                    }
            }
            continue;
        }
        if (fire && age % 5)
            continue;
        const auto owner = std::find_if(roster.begin(), roster.end(),
                                        [&](const Json &a) { return a.at("id") == f.at("player"); });
        if (owner == roster.end())
            throw std::invalid_argument("Отсутствует владелец гранаты");
        for (auto &a : roster) {
            auto pos = xyz(a);
            double d = distance(p, pos);
            if (a.at("hp") == 0 || d > radius || planner_->hit(p, pos, 1, 5, 64))
                continue;
            if (kind == "Свет") {
                int duration = int(std::nearbyint(7 + 19 * (1 - d / radius)));
                a["blind"] = std::max(a.at("blind").get<Tick>(), plus_ticks(now, duration));
                emit(w, "flash", a.at("name").get<std::string>() + " ослеплён", a.at("team"))
                    .update(Json{{"player", a.at("id")}, {"duration", duration}});
            } else {
                double amount = fire ? std::min(32., 8. + 4. * (age / 5))
                                     : std::max(0., std::nearbyint(98 * (1 - d / radius)));
                apply_impact(w, cfg, *owner, a, amount, kind, fire ? "fire" : "blast");
            }
        }
    }
}
} // namespace esport
