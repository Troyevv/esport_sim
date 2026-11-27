#pragma once
#include "tactic_execution.hpp"
#include "team_ai.hpp"

namespace esport {
Json rescue_c4(Json &w, const PhysicalNavigation &nav, const Squad &allies);

class AgentTurn {
  public:
    AgentTurn(Json &w, Json &actor, const Squad &squad, const Json &cfg, const OpeningMap &map,
              const Combat &combat, const Json &recovery);
    void prepare();
    void finish(const Json &intent);
    Json priority_intent();
    Json contact_decision();
    Json opening_decision();
    Point anticipated(const Json &report) const;
    Json &attention(Point &focus);
    Json plant_intercept(Point &goal, Point &watch, Json &cue);
    std::optional<Point> flank(Json &order, const Json &home);
    Point search_site(const std::string &site);
    Json postplant(std::string &site, const Json &order, const Json *latest, Point &goal, Point &watch);
    Json assist_contact(const Squad &allies, const Json &report);
    Json retake_utility(const std::string &site);
    Json spatial_intent();
    Json crossing(const Json &order, std::string site);
    Json hold_sector();
    Json prepare_plant(const std::string &site);
    bool smokes_plant(const std::string &site, const Point &p) const;
    Json select_contact() const;
    void service_weapon();
    Json seek_cover(const Json &contact);
    Json saved_exit();
    Json duel(const Json &contact);
    Json last_burst();
    bool screen_safe(const Point &point) const;

    bool move(const Point &point, double pace);
    Json movement(const Point &goal, double pace);
    bool clear(const Json &l, const Json &r) const;
    double gap(const Json &other) const { return distance(actor_point(a), actor_point(other)); }
    const std::string side;
    const Tick now;
    const int slot;
    Json &w;
    Json &a;
    const Squad &squad;
    const Json &cfg;
    const OpeningMap &arena;
    const GridMap *grid;
    Json grid_intent();
    Json grid_exit();
    Json grid_fire;
    const Combat &combat;
    const Json &recovery;
    const Json &player;
    const Json &skills;
    Json &plan;
    Json action, device;
    std::vector<Hazard> fire;
    bool opening_sight{};

  private:
    std::string previous;
    int step_index{};
    Point prior_position;
    void pickup();
    void duty_feedback();
    void check_incoming(const std::string &intent);
};
} // namespace esport
