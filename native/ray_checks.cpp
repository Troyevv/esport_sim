#include "physical_navigation.hpp"

#include <stdexcept>

int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    const std::vector<esport::Vertex> vertices{{0, 0, 0}, {10, 0, 0}, {0, 10, 0}};
    const std::vector<esport::Face> faces{{0, 1, 2}};
    for (int i = 0; i < 100; ++i) {
        auto scene =
            std::make_shared<esport::TriangleScene>(argv[1], vertices, faces, std::vector<std::uint8_t>{3});
        std::vector<RTCRayHit> rays(128);
        for (auto &item : rays) {
            item.ray.org_x = item.ray.org_y = 2;
            item.ray.org_z = -1;
            item.ray.dir_z = 1;
            item.ray.mask = 1;
            item.ray.tfar = 3;
        }
        scene->intersect(rays);
        for (const auto &item : rays) {
            if (item.hit.primID != 0 || item.ray.tfar != 1)
                throw std::runtime_error("Incorrect triangle hit");
        }
        using namespace esport;
        Primitive sphere{};
        sphere.inverse = {Point{1, 0, 0}, Point{0, 1, 0}, Point{0, 0, 1}};
        sphere.radius = 1;
        sphere.mask = 2;
        sphere.low = {-1, -1, -1};
        sphere.high = {1, 1, 1};
        auto world = std::make_shared<CollisionWorld>(scene, std::vector<unsigned short>{0},
                                                      std::vector<Primitive>(9, sphere));
        scene.reset();
        if (world->trace({-2, 0, 0}, {2, 0, 0}, 2) != Impact{.25, 0, std::nullopt})
            throw std::runtime_error("Incorrect analytic hit");
        std::map<AreaId, Point> centers{{1, {1, 1, 0}}};
        std::vector<Area> areas{{1, {{0, 0, 0}, {10, 0, 0}, {0, -10, 0}}}};
        PhysicalNavigation planner(world, PortalGraph::create(centers, {}),
                                   std::make_shared<NavSurfaces>(areas), {0, 0, 0}, 1, centers, areas, {},
                                   {});
        world.reset();
        if (!planner.path(1, {1, 1, 0}, 1, {2, 2, 0}, {}))
            throw std::runtime_error("Missing walkable path");
        MotionState actor{{1, 1, 0}, 1, 0, 0, {}, std::nullopt};
        for (int step = 0; step < 10; ++step)
            planner.walk(actor, {2, 2, 0}, .2, {});
        if (actor.position != Point{2, 2, 0} || !actor.path.empty())
            throw std::runtime_error("Incomplete walking step");
        if (planner.grenade({1, 1, 0}, {2, 2, 0}, 5).size() != 6)
            throw std::runtime_error("Incomplete flight");
    }
}
