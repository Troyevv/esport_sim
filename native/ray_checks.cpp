#include "rays.hpp"

#include <stdexcept>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::vector<esport::Vertex> vertices{{0, 0, 0}, {10, 0, 0}, {0, 10, 0}};
    const std::vector<esport::Face> faces{{0, 1, 2}};
    for (int i = 0; i < 100; ++i) {
        esport::TriangleScene scene(argv[1], vertices, faces, {3});
        std::vector<RTCRayHit> rays(128);
        for (auto& item : rays) {
            item.ray.org_x = item.ray.org_y = 2;
            item.ray.org_z = -1;
            item.ray.dir_z = 1;
            item.ray.mask = 1;
            item.ray.tfar = 3;
        }
        scene.intersect(rays);
        for (const auto& item : rays) {
            if (item.hit.primID != 0 || item.ray.tfar != 1)
                throw std::runtime_error("Incorrect triangle hit");
        }
    }
}
