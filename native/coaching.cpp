#include "coaching.hpp"
#include <algorithm>
#include <cmath>
#include <set>

namespace esport {
namespace {
int bounded(int value) { return std::clamp(value, 0, 100); }
int resistance(const Json &p, const Json &a) {
    const auto &s = p.at("skills");
    return (2*s.at("stress_resistance").get<int>() + s.at("composure").get<int>() +
            p.at("roleMastery").value(a.at("playingRole").get<std::string>(), 50))/4;
}
int base_confidence(const Json &p) {
    return (p.at("skills").at("confidence").get<int>() + p.at("form").get<int>() + 100)/4;
}
void shift(Json &m, const char *key, int change) {
    m.at(key) = bounded(m.at(key).get<int>() + change);
}
void attention(const Json &w, Json &a) {
    const auto &p = player_profile(w,a), &s = p.at("skills");
    auto &m = a.at("mind");
    const int stress = m.at("stress"), frustration = m.at("frustration"), confidence = m.at("confidence");
    const int activation = (20 - std::abs(stress - 35))/3;
    m["focus"] = std::clamp(activation - frustration/5 - p.at("fatigue").get<int>()/12 +
                            (s.at("concentration").get<int>()-50)/8, -22, 10);
    m["initiative"] = std::clamp((confidence-50)/3 + frustration/6 +
                          (s.at("motivation").get<int>() + p.at("morale").get<int>()-100)/12 -
                          std::max(0,stress-55)/3, -18, 22);
}
void topic(Json &a, Tick id, int round, std::string kind, std::string message) {
    auto &list = a.at("topics");
    if (!list.empty() && list.back().at("round") != round) list.clear();
    if (list.size() >= 4) list.erase(list.begin());
    list.push_back({{"id",id},{"round",round},{"kind",std::move(kind)},{"text",std::move(message)}});
}
const Json &coach(const Json &w, const Json &team) {
    return w.at("coaches").at(team.get<std::string>());
}
}
void initialize_mind(const Json &w, Json &a) {
    if (w.value("agentPolicy",0)<12 || a.contains("mind")) return;
    const auto &p = player_profile(w,a);
    a["mind"] = {{"confidence",base_confidence(p)},{"stress",12+p.at("fatigue").get<int>()/5},
                 {"frustration",0},{"focus",0},{"initiative",0}};
    a["topics"] = Json::array();
    attention(w,a);
}
void encounter_emotion(Json &w, Json &a, bool success, bool mistake, Tick event) {
    if (!a.contains("mind")) return;
    const int sensitivity = (115-resistance(player_profile(w,a),a))/12;
    auto &m = a.at("mind");
    shift(m,"confidence",success ? 3+sensitivity/2 : -2-sensitivity/2);
    shift(m,"stress",success ? -3 : 3+sensitivity);
    shift(m,"frustration",success ? -5 : (mistake ? 8 : 4)+sensitivity);
    topic(a,event,w.at("round"),success ? "success" : mistake ? "mistake" : "loss",
          success ? "Выиграл перестрелку. Готов снова взять первый контакт." :
          mistake ? "Задел своего. Нужно согласовать линию огня." :
                    "Проиграл дуэль. На следующем контакте хочу играть с разменом.");
    attention(w,a);
}
void round_emotion(Json &w, Json &a, bool won, int target) {
    if (!a.contains("mind")) return;
    const auto &p = player_profile(w,a);
    auto &m = a.at("mind");
    const int own = w.at("score").at(a.at("club").get<int>()), other = w.at("score").at(1-a.at("club").get<int>());
    const bool clutch = w.at("clutch").value(a.at("team").get<std::string>(),std::string{}) == a.at("id").get<std::string>();
    const bool refused = a.contains("lastRefusal");
    const auto &plan = w.at("plans").at(a.at("team").get<std::string>());
    const bool executed = plan.contains("board") && a.value("stepIndex",0)>0 && !refused;
    const int stakes = w.value("matchImportance",0) + (std::max(own,other)>=target-1 ? 18 : 0)
                       + (w.at("round")>24 ? 7 : 0) + std::clamp(other-own,0,9);
    const int sensitivity = 110-resistance(p,a);
    shift(m,"stress",(12+p.at("fatigue").get<int>()/4 + stakes*sensitivity/75 - m.at("stress").get<int>())/3 +
          (won ? -3 : 4) + (clutch && !won ? 5 : 0));
    shift(m,"confidence",(base_confidence(p)-m.at("confidence").get<int>())/6 +
          (won ? 3+(other>own) : -3) + (clutch ? (won ? 6 : -4) : 0) + int(executed)-int(refused)*2);
    shift(m,"frustration",-m.at("frustration").get<int>()/5 + (won ? -4 : 3) + (refused ? 5 : 0));
    if (refused)
        topic(a,w.at("serial"),w.at("round"),"execution","Не выполнил шаг плана: " + a.at("lastRefusal").at("reason").get<std::string>() + ".");
    else if (clutch || executed)
        topic(a,w.at("serial"),w.at("round"),won || executed ? "success" : "loss",
              clutch ? (won ? "Удалось забрать клатч." : "Остался один и проиграл клатч.") : "Выполнил свою часть плана.");
    attention(w,a);
}
void timeout_recovery(Json &w, const Json &team) {
    for (auto &a : w.at("agents")) if (a.at("teamId")==team && a.contains("mind")) {
        auto &m=a.at("mind");
        shift(m,"stress",-m.at("stress").get<int>()/7);
        shift(m,"frustration",-m.at("frustration").get<int>()/8);
        attention(w,a);
    }
}
void coach_address(Json &w, const Json &team, const Json &q) {
    const std::string target=q.at("target"), action=q.at("action");
    const Tick subject=q.at("subject");
    const bool order=action=="order";
    static const std::set<std::string> actions{"praise","mistake","critique","harsh","motivate","calm","support","focus","discipline","opinion","discuss","order"};
    static const std::set<std::string> orders{"cautious","aggressive","hold","discipline","trade","support","utility","position","tempo"};
    if (!actions.contains(action) || (order && (!orders.contains(q.value("order",std::string{})) || target=="team")))
        throw std::invalid_argument("Неизвестное обращение");
    const Json *fact=nullptr;
    bool selected=target=="team";
    for (const auto &a:w.at("agents")) if (a.at("teamId")==team) {
        selected |= a.at("id")==target;
        if (target!="team" && a.at("id")!=target) continue;
        for (const auto &t:a.at("topics")) if (subject && t.at("id")==subject && q.value("speaker",std::string{})==a.at("id").get<std::string>()) fact=&t;
    }
    if (!selected || (subject && !fact) || (!fact && (action=="mistake" || action=="discuss")))
        throw std::invalid_argument("Выберите наблюдение адресата");
    const Json evidence=fact ? *fact : Json(nullptr);
    const int cost=order || action=="discuss" ? 15 : 10;
    if (w.at("talkSeconds")<cost) throw std::invalid_argument("Время на разговор исчерпано");
    Json replies=Json::array();
    for (auto &a:w.at("agents")) {
        if (a.at("teamId")!=team || (target!="team" && a.at("id")!=target)) continue;
        const auto &p=player_profile(w,a), &s=p.at("skills");
        auto &m=a.at("mind");
        int repeats=0;
        for (const auto &row:w.at("talkHistory"))
            if (row.at("team")==team && row.at("action")==action &&
                (row.at("target")=="team" || row.at("target")==a.at("id"))) ++repeats;
        const int openness=(s.at("professionalism").get<int>()+resistance(p,a)+coach(w,team).at("support").get<int>())/3
                          -m.at("frustration").get<int>()/4-p.at("fatigue").get<int>()/8-12*repeats;
        const bool personal=fact && q.at("speaker")==a.at("id");
        std::string reply;
        if (order) {
            const auto duty=q.at("order");
            if (duty=="support") {
                const bool mate=std::ranges::any_of(w.at("agents"),[&](const auto &b) {
                    return b.at("teamId")==team && b.at("id")==q.value("mate",std::string{}) && b.at("id")!=a.at("id");
                });
                if (!mate) throw std::invalid_argument("Выберите напарника");
            }
            if ((duty=="position" || duty=="hold") && q.value("site",std::string{})!="A" && q.value("site",std::string{})!="B")
                throw std::invalid_argument("Выберите направление");
            a["coachOrder"]={{"kind",duty},{"mate",q.value("mate",std::string{})},{"site",q.value("site",std::string{})}};
            reply="Принял на ближайший раунд.";
        } else if (action=="opinion" || action=="discuss") {
            reply=personal ? evidence.at("text").get<std::string>() : !a.at("topics").empty() ?
                a.at("topics").back().at("text").get<std::string>() : m.at("stress")>40 ? "Напряжён. Давайте упростим первый контакт." : "Готов играть по плану капитана.";
        } else if (action=="harsh" || action=="critique" || action=="mistake" || action=="discipline") {
            const bool fair=personal && (evidence.at("kind")=="mistake" || evidence.at("kind")=="execution");
            if (fair && openness>(action=="harsh" ? 65 : 40)) {
                shift(m,"frustration",-4); shift(m,"stress",-3); reply="Согласен. В следующем раунде проверю этот момент.";
            } else if ((!fair || repeats) && openness<75) {
                shift(m,"frustration",action=="harsh" ? 8 : 4); shift(m,"stress",3); reply="Вижу этот эпизод иначе. Давайте разберём конкретное действие.";
            } else reply="Услышал.";
        } else if (action=="praise" && personal && evidence.at("kind")=="success" && openness>35) {
            shift(m,"confidence",4); reply="Спасибо. Готов взять инициативу.";
        } else if ((action=="calm" || action=="support" || action=="focus") && openness>35 && (m.at("stress")>28 || m.at("frustration")>18)) {
            shift(m,"stress",-std::max(1,openness/12)); shift(m,"frustration",-3); reply="Понял. Есть время выдохнуть и проверить план.";
        } else if (action=="motivate" && openness>48 && m.at("confidence")<52) {
            shift(m,"confidence",3); reply="Поборемся. Возьму свою задачу.";
        } else reply=repeats ? "Это уже обсуждали." : "Услышал, продолжаю по плану.";
        attention(w,a);
        replies.push_back({{"player",a.at("name")},{"text",reply}});
    }
    w.at("talkSeconds")=w.at("talkSeconds").get<int>()-cost;
    w.at("talkHistory").push_back({{"team",team},{"round",w.at("round")},{"target",target},{"action",action},
                                    {"subject",evidence},{"replies",std::move(replies)}});
}
int timeout_need(int distress,int mistakes,int deficit,int recent_losses,int economic_gap,int stakes,int round,int remaining,int quality) {
    if (!remaining) return -100;
    int reserve=std::max(0,17-round)*(4-std::min(3,remaining))/2;
    return distress + std::min(18,mistakes*5) + std::clamp(deficit*2,-8,14) + recent_losses*4 +
           economic_gap + stakes + quality/12 - reserve - 50;
}
void consider_break(Json &w) {
    if (w.value("agentPolicy",0)<12 || w.at("round")<3 || w.at("pending")==true) return;
    const int n=w.at("round");
    const bool autonomous=w.value("autonomous",false) || (w.contains("series") && w.at("series").value("spectator",false));
    int best=0; std::string chosen;
    for (const auto &captain:w.at("agents")) {
        if (!captain.at("appointed").get<bool>()) continue;
        const std::string team=captain.at("teamId"), side=captain.at("team");
        if ((!autonomous && w.at("coachTeamId")==team) || n-w.at("lastBreak").value(team,-10)<3) continue;
        int budget=w.at("coachTeamId")==team ? w.at("remaining").get<int>() : w.at("rivalRemaining").get<int>();
        int load=0, mistakes=0, cash=0, losses=0;
        for (const auto &a:w.at("agents")) if (a.at("teamId")==team) {
            const auto &m=a.at("mind");
            load+=m.at("stress").get<int>()/2+m.at("frustration").get<int>()+std::max(0,50-m.at("confidence").get<int>())/2;
            cash+=a.at("cash").get<int>();
            for (const auto &t:a.at("topics")) if (t.at("round")==n-1 && (t.at("kind")=="execution" || t.at("kind")=="loss" || t.at("kind")=="mistake")) ++mistakes;
        }
        const auto &history=w.at("history");
        for (int i=1;i<=std::min(3,int(history.size()));++i) losses+=history.at(history.size()-i).at("winnerTeamId")!=team;
        int gap=0;
        if (w.contains("opponentEconomy") && w.at("opponentEconomy").contains(side)) {
            int estimate=0;
            for (const auto &account:w.at("opponentEconomy").at(side)) estimate+=account.at("balance").get<int>();
            gap=std::clamp((estimate-cash)/3000,-4,6);
        }
        const int club=captain.at("club"), own=w.at("score")[club], other=w.at("score")[1-club];
        int value=timeout_need(load/5,mistakes,other-own,losses,gap,w.value("matchImportance",0)/3+
                        (std::max(own,other)>=11 ? 6 : 0),n,budget,coach(w,team).at("analysis"));
        if (value>best) {best=value; chosen=team;}
    }
    if (chosen.empty()) return;
    auto &budget=w.at(w.at("coachTeamId")==chosen ? "remaining" : "rivalRemaining");
    budget=budget.get<int>()-1;
    w.at("lastBreak")[chosen]=n;
    w["breakOwner"]=chosen;
    w.at("talkSeconds")=60;
    timeout_recovery(w,chosen);
    Json *target=nullptr;
    for (auto &a:w.at("agents")) if (a.at("teamId")==chosen &&
            (!target || a.at("mind").at("frustration")>target->at("mind").at("frustration"))) target=&a;
    const auto &topics=target->at("topics");
    Json request={{"target",target->at("id")},{"speaker",target->at("id")},{"subject",topics.empty()?Json(0):topics.back().at("id")},{"action","support"}};
    coach_address(w,chosen,request);
    request.update(Json{{"action","order"},{"order",coach(w,chosen).at("bold")==true ? "trade" : "cautious"}});
    coach_address(w,chosen,request);
    const auto plan=coach(w,chosen).at("bold")==true ? "Ускориться" : "Капитану";
    w["aiCall"]={{"team",chosen},{"plan",plan}};
    w["deadline"]=plus_ticks(w.at("deadline"),60);
    emit(w,"timeout",w.at("domain").at("teams").at(chosen).at("name").get<std::string>()+" берёт тактический тайм-аут");
}
}
