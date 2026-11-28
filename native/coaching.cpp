#include "coaching.hpp"
#include <algorithm>
#include <cmath>
#include <set>

namespace esport {
namespace {
int bounded(int value) { return std::clamp(value, 0, 100); }
int resistance(const Json &p, const Json &a) {
    const auto &s = p.at("skills");
    return (2 * s.at("stress_resistance").get<int>() + s.at("composure").get<int>() +
            p.at("roleMastery").value(a.at("playingRole").get<std::string>(), 50)) /
           4;
}
int base_confidence(const Json &p) {
    return (p.at("skills").at("confidence").get<int>() + p.at("form").get<int>() + 100) / 4;
}
void shift(Json &m, const char *key, int change) { m.at(key) = bounded(m.at(key).get<int>() + change); }
void attention(const Json &w, Json &a) {
    const auto &p = player_profile(w, a), &s = p.at("skills");
    auto &m = a.at("mind");
    const int stress = m.at("stress"), frustration = m.at("frustration"), confidence = m.at("confidence");
    const int activation = (20 - std::abs(stress - 35)) / 3;
    m["focus"] = std::clamp(activation - frustration / 5 - p.at("fatigue").get<int>() / 12 +
                                (s.at("concentration").get<int>() - 50) / 8,
                            -22, 10);
    m["initiative"] = std::clamp((confidence - 50) / 3 + frustration / 6 +
                                     (s.at("motivation").get<int>() + p.at("morale").get<int>() - 100) / 12 -
                                     std::max(0, stress - 55) / 3,
                                 -18, 22);
}
void topic(Json &a, Tick id, int round, std::string kind, std::string message) {
    auto &list = a.at("topics");
    if (!list.empty() && list.back().at("round") > round)
        return;
    if (!list.empty() && list.back().at("round") != round)
        list.clear();
    for (const auto &prior : list)
        if (prior.at("id") == id)
            return;
    if (list.size() >= 4)
        list.erase(list.begin());
    list.push_back({{"id", id}, {"round", round}, {"kind", std::move(kind)}, {"text", std::move(message)}});
}
void report_episode(Json &a, Tick event, int round, const std::string &kind, const std::string &issue,
                    std::string fact, std::string inference, std::string proposal) {
    const auto last = a.value("lastConcern", Json::object());
    const bool repeated = last.value("issue", std::string{}) == issue && last.value("round", 0) >= round - 2;
    a["lastConcern"] = {{"issue", issue},
                        {"round", round},
                        {"count", repeated ? std::min(5, last.value("count", 1) + 1) : 1}};
    if (repeated && !inference.empty())
        inference = "Похожий эпизод уже был. " + inference;
    std::string text = fact;
    if (!inference.empty())
        text += " " + inference;
    if (!proposal.empty())
        text += " " + proposal;
    topic(a, event, round, kind, text);
    auto &topics = a.at("topics");
    auto it = std::ranges::find_if(topics, [&](const auto &row) { return row.at("id") == event; });
    if (it == topics.end())
        return;
    auto &row = *it;
    row.update({{"issue", issue},
                {"observation", std::move(fact)},
                {"inference", std::move(inference)},
                {"proposal", std::move(proposal)},
                {"repeated", repeated}});
}
const Json &coach(const Json &w, const Json &team) { return w.at("coaches").at(team.get<std::string>()); }
} // namespace
void initialize_mind(const Json &w, Json &a) {
    if (w.value("agentPolicy", 0) < 12 || a.contains("mind"))
        return;
    const auto &p = player_profile(w, a);
    a["mind"] = {{"confidence", base_confidence(p)},
                 {"stress", 12 + p.at("fatigue").get<int>() / 5},
                 {"frustration", 0},
                 {"focus", 0},
                 {"initiative", 0}};
    a["topics"] = Json::array();
    attention(w, a);
}
void encounter_emotion(Json &w, Json &a, bool success, bool mistake, Tick event, const std::string &weapon) {
    if (!a.contains("mind"))
        return;
    const int sensitivity = (115 - resistance(player_profile(w, a), a)) / 12;
    auto &m = a.at("mind");
    shift(m, "confidence", success ? 3 + sensitivity / 2 : -2 - sensitivity / 2);
    shift(m, "stress", success ? -3 : 3 + sensitivity);
    shift(m, "frustration", success ? -5 : (mistake ? 8 : 4) + sensitivity);
    const auto now = w.at("tick").get<Tick>();
    const auto round = w.at("round").get<int>();
    const bool grenade = weapon == "HE" || weapon == "Огонь" || weapon == "C4";
    const std::string fact =
        success   ? (grenade ? "Устранение с помощью " + weapon + "." : "Выиграл контакт с " + weapon + ".")
        : mistake ? "Задел своего."
        : grenade ? "Выбыл от " + weapon + "."
                  : "Проиграл перестрелку.";
    const bool alone = std::ranges::none_of(w.at("agents"), [&](const auto &mate) {
        return mate.at("team") == a.at("team") && mate.at("id") != a.at("id") && mate.at("hp") > 0 &&
               distance(actor_point(a), actor_point(mate)) < 26;
    });
    const auto &vis = a.at("visible");
    const bool careful = player_profile(w, a).at("skills").at("professionalism") > 60;
    std::string where;
    if (a.contains("decision")) {
        const auto &d = a.at("decision");
        if (d.contains("site"))
            where = " Моя задача была на " + d.at("site").get<std::string>() + ".";
    }
    if (where.empty()) {
        const auto &plans = w.at("plans");
        auto side = plans.find(a.at("team").get<std::string>());
        if (side != plans.end() && side->contains("orders")) {
            const auto &slot = side->at("orders").at("slots").at(a.at("slot").get<int>());
            if (slot.contains("site"))
                where = " Задача на " + slot.at("site").get<std::string>() + ".";
        }
    }
    const bool warned = std::ranges::any_of(a.at("knowledge"), [&](const auto &r) {
        return r.at("source") == "Радио" && now - r.at("tick").template get<Tick>() <= 12;
    });
    if (warned)
        where += " Перед контактом слышал свежий доклад.";
    if (!vis.empty()) {
        const auto key = vis.front().get<std::string>();
        const auto &knowledge = a.at("knowledge");
        if (knowledge.contains(key)) {
            const auto &seen = knowledge.at(key);
            const double bearing = std::atan2(seen.at("y").get<double>() - a.at("y").get<double>(),
                                              seen.at("x").get<double>() - a.at("x").get<double>()) -
                                   a.at("heading").get<double>();
            where += std::cos(bearing) > .65 ? " Контакт передо мной."
                     : std::sin(bearing) > 0 ? " Контакт сбоку слева."
                                             : " Контакт сбоку справа.";
        }
    }
    if (mistake)
        report_episode(a, event, round, "mistake", "friendly_fire", fact,
                       "Возможно, не согласовали движение.", "Давайте разведём позиции.");
    else if (!success && a.value("flashLevel", 0.) >= .45)
        report_episode(a, event, round, "loss", "flash", fact + " На контакте плохо видел после флешки.", {},
                       "Предупреждайте о выходе по радио.");
    else if (!success && a.at("reloadAt").get<Tick>() > now)
        report_episode(a, event, round, "loss", "reload", fact + " Перезаряжался.", {},
                       "Попрошу прикрыть перезарядку.");
    else if (!success && grenade)
        report_episode(a, event, round, "loss", "utility", fact + where, {},
                       "Посмотрим, был ли другой маршрут.");
    else if (!success && vis.size() > 1)
        report_episode(a, event, round, "loss", "multiple",
                       fact + " Видел сразу " + std::to_string(vis.size()) + " соперников." + where,
                       careful ? "Похоже, угол оказался слишком широким." : std::string{},
                       "Попробуем сузить первый контакт.");
    else if (!success && alone && !vis.empty())
        report_episode(a, event, round, "loss", "isolated",
                       fact + " По радару рядом не было напарника." + where,
                       "Возможно, разошлись по времени.", "Сверим мой выход с ближайшим партнёром.");
    else if (!success && vis.empty())
        report_episode(a, event, round, "loss", "unseen", fact + " Сам стрелявшего не видел." + where, {},
                       "Кто видел контакт? Сверим доклады.");
    else if (success && !alone)
        report_episode(a, event, round, "success", "pair", fact + " Напарник был рядом." + where, {},
                       "Готов повторить эту расстановку.");
    else
        report_episode(a, event, round, success ? "success" : "loss", "duel", fact + where, {},
                       success && m.at("confidence") > 65 ? "Готов снова принять первый контакт."
                       : careful                          ? "Хочу сверить эпизод с тем, что видел напарник."
                                                          : "");
    attention(w, a);
}
void self_flash_emotion(Json &w, Json &a, Tick event) {
    if (!a.contains("mind"))
        return;
    auto &m = a.at("mind");
    shift(m, "frustration", 2 + (100 - resistance(player_profile(w, a), a)) / 20);
    report_episode(a, event, w.at("round"), "mistake", "self_flash", "Ослепил себя своей флешкой.", {},
                   "Сверим момент броска и выхода.");
    attention(w, a);
}
void round_emotion(Json &w, Json &a, bool won, int target, Tick round_event, bool overtime) {
    if (!a.contains("mind"))
        return;
    const auto &p = player_profile(w, a);
    auto &m = a.at("mind");
    const int own = w.at("score").at(a.at("club").get<int>()),
              other = w.at("score").at(1 - a.at("club").get<int>());
    const bool clutch =
        w.at("clutch").value(a.at("team").get<std::string>(), std::string{}) == a.at("id").get<std::string>();
    const bool refused = a.contains("lastRefusal");
    const auto plan = w.at("plans").find(a.at("team").get<std::string>());
    const bool executed =
        plan != w.at("plans").end() && plan->contains("board") && a.value("stepIndex", 0) > 0 && !refused;
    const auto &domain = w.at("domain");
    const int opposition = domain.contains("oppositionPressure")
                               ? domain.at("oppositionPressure").value(a.at("teamId").get<std::string>(), 0)
                               : 0;
    const int stakes = opposition + w.value("matchImportance", 0) +
                       (std::max(own, other) >= target - 1 ? 18 : 0) + (overtime ? 7 : 0) +
                       std::clamp(other - own, 0, 9);
    const int sensitivity = 110 - resistance(p, a);
    shift(m, "stress",
          (12 + p.at("fatigue").get<int>() / 4 + stakes * sensitivity / 75 - m.at("stress").get<int>()) / 3 +
              (won ? -3 : 4) + (clutch && !won ? 5 : 0));
    shift(m, "confidence",
          (base_confidence(p) - m.at("confidence").get<int>()) / 6 + (won ? 3 + (other > own) : -3) +
              (clutch ? (won ? 6 : -4) : 0) + int(executed) - int(refused) * 2);
    shift(m, "frustration", -m.at("frustration").get<int>() / 5 + (won ? -4 : 3) + (refused ? 5 : 0));
    if (refused)
        topic(a, a.at("lastRefusal").value("event", round_event), w.at("round"), "execution",
              "Не выполнил шаг плана: " + a.at("lastRefusal").at("reason").get<std::string>() + ".");
    else if (clutch || executed)
        topic(a, round_event, w.at("round"), won || executed ? "success" : "loss",
              clutch ? (won ? "Удалось забрать клатч." : "Остался один и проиграл клатч.")
                     : "Выполнил свою часть плана.");
    int impact = 0;
    for (const auto &kill : w.at("kills"))
        if (kill.at("enemy") == true && (kill.at("player") == a.at("id") ||
                                         std::find(kill.at("assists").begin(), kill.at("assists").end(),
                                                   a.at("id")) != kill.at("assists").end()))
            ++impact;
    Json review = {
        {"round", w.at("round")}, {"won", won},
        {"executed", executed},   {"refused", refused},
        {"impact", impact},       {"site", plan != w.at("plans").end() ? plan->at("site") : Json(nullptr)}};
    const auto &history = w.at("history");
    if (won && history.size() >= 3 && own >= other &&
        history.at(history.size() - 3).at("score").at(a.at("club").get<int>()).get<int>() <
            history.at(history.size() - 3).at("score").at(1 - a.at("club").get<int>()).get<int>()) {
        review["comeback"] = true;
        shift(m, "confidence", 2);
        shift(m, "stress", -2);
    }
    // Team losses and the opening frag are public. Private refusals need a delivered report.
    const auto &kills = w.at("kills");
    if (!won && !kills.empty() && kills.front().at("enemy") == true &&
        std::ranges::any_of(w.at("agents"), [&](const auto &mate) {
            return mate.at("team") == a.at("team") && mate.at("id") == kills.front().at("player");
        }))
        shift(m, "frustration", 2);
    if (a.contains("peerCalls")) {
        for (const auto &call : a.at("peerCalls")) {
            if (call.at("state") != "refused" || !call.contains("reason"))
                continue;
            shift(m, "stress", 1);
            topic(a, round_event, w.at("round"), "execution_report",
                  "По радио сообщили, что шаг плана сорвался: " + call.at("reason").get<std::string>() + ".");
            break;
        }
    }
    a["roundReview"] = std::move(review);
    attention(w, a);
}
void timeout_recovery(Json &w, const Json &team) {
    for (auto &a : w.at("agents"))
        if (a.at("teamId") == team && a.contains("mind")) {
            const auto &e = a.at("evidence");
            if (e.is_object() && e.at("round").get<int>() >= w.at("round").get<int>() - 1)
                topic(a, e.at("id"), e.at("round"), "observation", e.at("text"));
            auto &m = a.at("mind");
            shift(m, "stress", -m.at("stress").get<int>() / 7);
            shift(m, "frustration", -m.at("frustration").get<int>() / 8);
            attention(w, a);
        }
}
void spend_talk_time(Json &w, int seconds) {
    if (!w.contains("talkSeconds"))
        return;
    const int remaining = w.at("talkSeconds");
    if (remaining < seconds)
        throw std::invalid_argument("Время на разговор исчерпано");
    w.at("talkSeconds") = remaining - seconds;
}
void coach_address(Json &w, const Json &team, const Json &q) {
    const std::string target = q.at("target"), action = q.at("action");
    const Tick subject = q.at("subject");
    const bool order = action == "order";
    static const std::set<std::string> actions{"praise",     "mistake", "critique", "harsh",
                                               "motivate",   "calm",    "support",  "focus",
                                               "discipline", "opinion", "discuss",  "order"};
    static const std::set<std::string> orders{"cautious", "aggressive", "hold",     "discipline", "trade",
                                              "support",  "utility",    "position", "tempo"};
    if (!actions.contains(action) ||
        (order && (!orders.contains(q.value("order", std::string{})) || target == "team")))
        throw std::invalid_argument("Неизвестное обращение");
    const Json *fact = nullptr;
    bool selected = target == "team";
    for (const auto &a : w.at("agents"))
        if (a.at("teamId") == team) {
            selected |= a.at("id") == target;
            if (target != "team" && a.at("id") != target)
                continue;
            for (const auto &t : a.at("topics"))
                if (subject && t.at("id") == subject &&
                    q.value("speaker", std::string{}) == a.at("id").get<std::string>())
                    fact = &t;
        }
    if (!selected || (subject && !fact) || (!fact && (action == "mistake" || action == "discuss")))
        throw std::invalid_argument("Выберите наблюдение адресата");
    const Json evidence = fact ? *fact : Json(nullptr);
    const int cost = order || action == "discuss" ? 15 : 10;
    if (w.at("talkSeconds") < cost)
        throw std::invalid_argument("Время на разговор исчерпано");
    int shared_errors = 0;
    if (target == "team")
        for (const auto &member : w.at("agents")) {
            if (member.at("teamId") != team || !member.contains("roundReview"))
                continue;
            const auto &r = member.at("roundReview");
            if (r.at("round") == w.at("round").get<int>() - 1 && r.at("refused") == true)
                ++shared_errors;
        }
    Json replies = Json::array();
    for (auto &a : w.at("agents")) {
        if (a.at("teamId") != team || (target != "team" && a.at("id") != target))
            continue;
        const auto &p = player_profile(w, a), &s = p.at("skills");
        auto &m = a.at("mind");
        int repeats = 0;
        for (const auto &row : w.at("talkHistory"))
            if (row.at("team") == team && row.at("action") == action &&
                (row.at("target") == "team" || row.at("target") == a.at("id")))
                ++repeats;
        const int openness = (s.at("professionalism").get<int>() + resistance(p, a) +
                              coach(w, team).at("support").get<int>()) /
                                 3 -
                             m.at("frustration").get<int>() / 4 - p.at("fatigue").get<int>() / 8 -
                             12 * repeats;
        const bool personal = fact && q.at("speaker") == a.at("id");
        const auto review = a.find("roundReview");
        const bool collective =
            target == "team" && review != a.end() && review->at("round") == w.at("round").get<int>() - 1;
        const bool contribution = collective && (review->at("impact") > 0 || review->at("executed") == true);
        const bool team_win = collective && review->at("won") == true;
        std::string reply;
        if (order) {
            const auto duty = q.at("order");
            if (duty == "support") {
                const bool mate = std::ranges::any_of(w.at("agents"), [&](const auto &b) {
                    return b.at("teamId") == team && b.at("id") == q.value("mate", std::string{}) &&
                           b.at("id") != a.at("id");
                });
                if (!mate)
                    throw std::invalid_argument("Выберите напарника");
            }
            if ((duty == "position" || duty == "hold") && q.value("site", std::string{}) != "A" &&
                q.value("site", std::string{}) != "B")
                throw std::invalid_argument("Выберите направление");
            a["coachOrder"] = {{"kind", duty},
                               {"mate", q.value("mate", std::string{})},
                               {"site", q.value("site", std::string{})}};
            reply = "Принял на ближайший раунд.";
        } else if (action == "opinion" || action == "discuss") {
            reply = personal                  ? evidence.at("text").get<std::string>()
                    : !a.at("topics").empty() ? a.at("topics").back().at("text").get<std::string>()
                    : m.at("stress") > 40     ? "Напряжён. Давайте упростим первый контакт."
                                              : "Готов играть по плану капитана.";
        } else if (action == "harsh" || action == "critique" || action == "mistake" ||
                   action == "discipline") {
            const bool fair =
                (personal && (evidence.at("kind") == "mistake" || evidence.at("kind") == "execution")) ||
                (collective && !team_win && review->at("refused") == true);
            if (fair && openness > (action == "harsh" ? 65 : 40)) {
                shift(m, "frustration", -4);
                shift(m, "stress", -3);
                reply = "Согласен. В следующем раунде проверю этот момент.";
            } else if (collective && shared_errors >= 2 && !team_win && !repeats &&
                       review->at("refused") == false && openness > 45 && action != "harsh") {
                reply = contribution ? "Свою часть сделал. Помогу сверить готовность перед выходом."
                                     : "Сверим задачи вместе, прежде чем начинать.";
                if (m.at("stress") > 35)
                    shift(m, "stress", -1);
            } else if ((!fair || repeats) && openness < 75) {
                const int sensitivity = (100 - resistance(p, a)) / 20;
                shift(m, "frustration", (action == "harsh" ? 6 : 2) + sensitivity);
                shift(m, "stress", 1 + sensitivity);
                reply = "Вижу этот эпизод иначе. Давайте разберём конкретное действие.";
            } else
                reply = "Услышал.";
        } else if (action == "praise" && collective && team_win && !repeats) {
            if (contribution && openness > 35 && m.at("confidence") < 80) {
                shift(m, "confidence", review->value("comeback", false) ? 4 : 2);
                reply = review->at("executed") == true ? "Сработал наш план. Свою часть готов повторить."
                                                       : "Спасибо, в этом раунде помог команде.";
            } else if (review->at("refused") == true || m.at("frustration") > 30) {
                reply = "Победа общая, но свой эпизод я ещё хочу разобрать.";
            } else if (openness > 50 && m.at("stress") > 35) {
                shift(m, "stress", -2);
                reply = "Теперь спокойнее. Сохраним темп.";
            } else
                reply = "За пятёрку рад. Что делаем дальше?";
        } else if (action == "praise" && personal && evidence.at("kind") == "success" && openness > 35) {
            shift(m, "confidence", 4);
            reply = "Спасибо. Готов взять инициативу.";
        } else if ((action == "calm" || action == "support" || action == "focus") && openness > 35 &&
                   (m.at("stress") > 28 || m.at("frustration") > 18)) {
            shift(m, "stress", -std::max(1, openness / 12));
            shift(m, "frustration", -3);
            reply = "Понял. Есть время выдохнуть и проверить план.";
        } else if (action == "motivate" && openness > 48 && m.at("confidence") < 52) {
            shift(m, "confidence", 3);
            reply = "Поборемся. Возьму свою задачу.";
        } else
            reply = repeats ? "Это уже обсуждали." : "Услышал, продолжаю по плану.";
        attention(w, a);
        replies.push_back({{"player", a.at("name")}, {"text", reply}});
    }
    spend_talk_time(w, cost);
    w.at("talkHistory")
        .push_back({{"team", team},
                    {"round", w.at("round")},
                    {"target", target},
                    {"action", action},
                    {"subject", evidence},
                    {"replies", std::move(replies)}});
}
int timeout_need(int distress, int mistakes, int deficit, int recent_losses, int economic_gap, int stakes,
                 int rounds_left, int remaining, int quality) {
    if (!remaining)
        return -100;
    int reserve = std::max(0, rounds_left - remaining) / std::max(1, remaining);
    return distress + std::min(18, mistakes * 5) + std::clamp(deficit * 2, -8, 14) + recent_losses * 4 +
           economic_gap + stakes + quality / 12 - reserve - 50;
}
void finish_ai_break(Json &w, Tick now) {
    if (w.contains("breakEnds") && now >= w.at("breakEnds").get<Tick>()) {
        w.erase("breakEnds");
        w.erase("breakOwner");
    }
}
int break_seconds(const Json &w, const Json &rules) {
    const int duration = rules.at("timeoutSeconds");
    return w.contains("series") ? w.at("series").at("profile").value("timeoutSeconds", duration) : duration;
}
int repeat_cost(int elapsed, int prior, int current, bool won, int stakes) {
    const int relief = std::max(0, prior - current);
    const int deterioration = std::max(0, current - prior);
    return std::max(0, (16 + std::min(15, relief) + (won ? 8 : 0) - deterioration - stakes / 2) /
                           std::max(1, elapsed));
}
namespace {
struct Intervention {
    int value, cost;
    std::string category;
    Json request;
};
void use_break(Json &w, const std::string &team) {
    std::vector<Intervention> options;
    const auto &staff = coach(w, team);
    int analysis = staff.at("analysis"), empathy = staff.at("support"), anxious = 0, failed = 0;
    const bool bold = staff.at("bold");
    const Json *captain = nullptr;
    auto add = [&](int value, int cost, std::string category, Json request) {
        for (const auto &r : w.at("talkHistory")) {
            if (r.at("team") == team && r.at("target") == request.at("target") &&
                r.at("action") == request.at("action") &&
                w.at("round").get<int>() - r.at("round").get<int>() <= 3)
                value -= 6;
        }
        options.push_back({value, cost, std::move(category), std::move(request)});
    };
    for (const auto &a : w.at("agents")) {
        if (a.at("teamId") != team)
            continue;
        const auto &m = a.at("mind");
        const auto id = a.at("id").get<std::string>();
        if (a.at("appointed") == true)
            captain = &a;
        int stress = m.at("stress"), frustration = m.at("frustration"), confidence = m.at("confidence");
        anxious += stress >= 38 || frustration >= 35;
        Json q = {{"target", id}, {"speaker", id}, {"subject", 0}, {"action", "support"}};
        add(std::max(stress - 15, frustration - 8) + std::max(0, 50 - confidence) / 2 + empathy / 5, 10,
            "personal", q);
        if (stress > frustration) {
            q["action"] = "calm";
            add(stress - 12 + empathy / 5, 10, "personal", q);
        }
        for (const auto &t : a.at("topics")) {
            if (t.at("round") != w.at("round").get<int>() - 1)
                continue;
            const auto issue = t.value("issue", std::string{});
            const int repeated = t.value("repeated", false) ? 14 : 0;
            q["subject"] = t.at("id");
            q["action"] = "discuss";
            if (t.at("kind") == "execution" || t.at("kind") == "mistake") {
                ++failed;
                q["action"] = "mistake";
                add(32 + analysis / 4 + repeated, 10, "analysis", q);
                q["action"] = "discipline";
                add(24 + analysis / 5 + repeated + (bold ? 0 : 6), 10, "analysis", q);
            } else if (t.at("kind") == "loss")
                add(15 + analysis / 5 + repeated, 15, "analysis", q);
            std::string order;
            if (issue == "self_flash" || issue == "flash" || issue == "utility")
                order = "utility";
            else if (issue == "isolated" || issue == "reload")
                order = "support";
            else if (issue == "friendly_fire" || t.at("kind") == "execution")
                order = "discipline";
            else if (issue == "multiple")
                order = "position";
            else if (issue == "pair" && bold && repeated)
                order = "trade";
            if (order.empty())
                continue;
            auto task = q;
            task["action"] = "order";
            task["order"] = order;
            if (order == "position") {
                if (!a.contains("roundReview") || a.at("roundReview").at("site").is_null())
                    continue;
                task["site"] = a.at("roundReview").at("site");
            }
            if (order == "support") {
                const Json *mate = nullptr;
                for (const auto &b : w.at("agents"))
                    if (b.at("teamId") == team && b.at("id") != a.at("id") &&
                        (!mate || b.at("mind").at("focus") > mate->at("mind").at("focus")))
                        mate = &b;
                if (!mate)
                    continue;
                task["mate"] = mate->at("id");
            }
            add(21 + analysis / 4 + repeated + (order == "trade" && bold ? 6 : 0), 15, "orders", task);
        }
    }
    if (!captain)
        return;
    Json team_talk = {{"target", "team"}, {"subject", 0}, {"action", "calm"}};
    add(anxious * 9 + empathy / 5, 10, "team", team_talk);
    team_talk["action"] = "discipline";
    add(failed * 10 + analysis / 5, 10, "team", team_talk);
    if (captain->contains("roundReview") && captain->at("roundReview").value("comeback", false)) {
        team_talk["action"] = "praise";
        add(36 + empathy / 5, 10, "team", team_talk);
    }
    // Keep the captain's plan unless a supported adjustment outvalues continuity.
    const int retain = 24 + analysis / 8;
    int best = retain;
    std::string plan = "Капитану";
    auto propose = [&](int value, std::string next) {
        if (value > best) {
            best = value;
            plan = std::move(next);
        }
    };
    auto h = w.find("siteHistory");
    if (captain->at("team") == "T" && h != w.end() && h->contains(team)) {
        const auto &sites = h->at(team);
        if (!sites.empty()) {
            const auto &last = sites.back();
            int losses = 0, won = 0;
            for (const auto &r : sites)
                if (r.at(0) == last.at(0)) {
                    if (r.at(1) == true)
                        ++won;
                    else
                        ++losses;
                }
            if (last.at(1) == false)
                propose(12 * (losses - won) + analysis / 5, last.at(0) == "A" ? "Выход B" : "Выход A");
        }
    }
    if (bold && anxious <= 2 && failed < 2 && captain->at("mind").at("confidence") >= 54)
        propose(20 + analysis / 5 + captain->at("mind").at("initiative").get<int>() / 2, "Ускориться");
    if (plan != "Капитану") {
        Json call = {{"action", "call"}, {"target", "team"}, {"subject", 0}, {"plan", plan}};
        add(best, 10, "plan", call);
    }
    std::stable_sort(options.begin(), options.end(),
                     [](const auto &l, const auto &r) { return l.value > r.value; });
    Json review = {{"round", w.at("round")},         {"team", team},
                   {"seconds", w.at("talkSeconds")}, {"retain", retain},
                   {"alternatives", Json::object()}, {"chosen", Json::array()}};
    std::set<std::string> used;
    for (const auto &option : options) {
        if (!review["alternatives"].contains(option.category))
            review["alternatives"][option.category] = option.value;
        if (option.value < 24 || option.cost > w.at("talkSeconds") || used.contains(option.category))
            continue;
        if (option.category == "team" && used.contains("personal") && anxious < 3)
            continue;
        if (option.category == "personal" && used.contains("team") && option.value < 42)
            continue;
        const auto &q = option.request;
        if (option.category == "plan") {
            spend_talk_time(w, option.cost);
            w["aiCall"] = {{"team", team}, {"plan", q.at("plan")}};
        } else
            coach_address(w, team, q);
        review["chosen"].push_back(q);
        used.insert(option.category);
    }
    review["secondsLeft"] = w.at("talkSeconds");
    w["breakDecisions"].push_back(std::move(review));
}
} // namespace
void consider_break(Json &w, const Json &rules) {
    if (w.value("agentPolicy", 0) < 12 || w.at("history").empty() || w.at("pending") == true)
        return;
    const int n = w.at("round");
    const bool autonomous =
        w.value("autonomous", false) || (w.contains("series") && w.at("series").value("spectator", false));
    int best = 0;
    std::string chosen;
    int chosen_load = 0;
    for (const auto &captain : w.at("agents")) {
        if (!captain.at("appointed").get<bool>())
            continue;
        const std::string team = captain.at("teamId"), side = captain.at("team");
        if (!autonomous && w.at("coachTeamId") == team)
            continue;
        int budget =
            w.at("coachTeamId") == team ? w.at("remaining").get<int>() : w.at("rivalRemaining").get<int>();
        int load = 0, mistakes = 0, cash = 0, losses = 0;
        for (const auto &a : w.at("agents"))
            if (a.at("teamId") == team) {
                const auto &m = a.at("mind");
                load += m.at("stress").get<int>() / 2 + m.at("frustration").get<int>() +
                        std::max(0, 50 - m.at("confidence").get<int>()) / 2;
                cash += a.at("cash").get<int>();
                for (const auto &t : a.at("topics"))
                    if (t.at("round") == n - 1 &&
                        (t.at("kind") == "execution" || t.at("kind") == "loss" || t.at("kind") == "mistake"))
                        ++mistakes;
            }
        const auto &history = w.at("history");
        for (int i = 1; i <= std::min(3, int(history.size())); ++i)
            losses += history.at(history.size() - i).at("winnerTeamId") != team;
        int gap = 0;
        if (w.contains("opponentEconomy") && w.at("opponentEconomy").contains(side)) {
            int estimate = 0;
            for (const auto &account : w.at("opponentEconomy").at(side))
                estimate += account.at("balance").get<int>();
            gap = std::clamp((estimate - cash) / 3000, -4, 6);
        }
        const int club = captain.at("club"), own = w.at("score")[club], other = w.at("score")[1 - club];
        const int target = round_target(n, rules);
        int stakes = w.value("matchImportance", 0) / 3 + (std::max(own, other) >= target - 1 ? 8 : 0) +
                     (n > 2 * rules.at("half").get<int>() ? 4 : 0);
        if (w.contains("series")) {
            const auto &series = w.at("series");
            if (series.at("bestOf") > 1 &&
                series.at("score").at(team).get<int>() == series.at("bestOf").get<int>() / 2)
                stakes += 3;
        }
        const int distress = load / 5;
        int value = timeout_need(distress, mistakes, other - own, losses, gap, stakes,
                                 target - std::max(own, other), budget, coach(w, team).at("analysis"));
        if (w.at("lastBreak").contains(team))
            value -= repeat_cost(n - w.at("lastBreak").at(team).get<int>(),
                                 w.value("breakLoad", Json::object()).value(team, distress), distress,
                                 history.back().at("winnerTeamId") == team, stakes);
        if (value > best) {
            best = value;
            chosen = team;
            chosen_load = distress;
        }
    }
    if (chosen.empty())
        return;
    auto &budget = w.at(w.at("coachTeamId") == chosen ? "remaining" : "rivalRemaining");
    budget = budget.get<int>() - 1;
    w.at("lastBreak")[chosen] = n;
    w["breakOwner"] = chosen;
    w["breakLoad"][chosen] = chosen_load;
    const int seconds = break_seconds(w, rules);
    w.at("talkSeconds") = seconds;
    timeout_recovery(w, chosen);
    use_break(w, chosen);
    w["breakEnds"] = plus_ticks(w.at("tick"), seconds * 10);
    w["deadline"] = plus_ticks(w.at("deadline"), seconds * 10);
    emit(w, "timeout",
         w.at("domain").at("teams").at(chosen).at("name").get<std::string>() + " берёт тактический тайм-аут");
}
} // namespace esport
