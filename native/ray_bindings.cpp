#include "rays.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <pybind11/numpy.h>
#include <pybind11/stl/filesystem.h>

namespace py = pybind11;

namespace {
template<class T>
using Array = py::array_t<T, py::array::c_style | py::array::forcecast>;

template<class T>
std::vector<std::array<T, 3>> triples(const Array<T>& array, bool pad = false) {
    if (array.ndim() != 2 || array.shape(1) != 3) throw py::value_error("Expected an N x 3 array");
    static_assert(sizeof(std::array<T, 3>) == sizeof(T) * 3);
    std::vector<std::array<T, 3>> result;
    result.reserve(array.shape(0) + static_cast<std::size_t>(pad));
    result.resize(array.shape(0));
    if (!result.empty()) std::memcpy(result.data(), array.data(), array.nbytes());
    return result;
}

std::unique_ptr<esport::TriangleScene> make_scene(
    const Array<float>& vertices, const Array<std::int32_t>& faces, const Array<std::uint8_t>& masks) {
    if (masks.ndim() != 1) throw py::value_error("Expected one mask per face");
    auto points = triples(vertices, true);
    auto triangles = triples(faces);
    std::vector<std::uint8_t> channels(masks.data(), masks.data() + masks.size());
    // The installed wheel resolves its dependencies before we take a library reference.
    auto path = py::module_::import("backend.cs2_rays").attr("_library_path")().cast<std::filesystem::path>();
    py::gil_scoped_release release;
    return std::make_unique<esport::TriangleScene>(path, std::move(points), triangles, channels);
}

py::tuple first_many(const esport::TriangleScene& scene, const Array<float>& starts,
                     const Array<float>& directions, const Array<float>& limits, unsigned channel) {
    if (starts.ndim() != 2 || starts.shape(1) != 3) throw py::value_error("Expected N x 3 origins");
    const auto n = starts.shape(0);
    const bool uniform = (directions.ndim() == 1 && directions.shape(0) == 3) ||
                         (directions.ndim() == 2 && directions.shape(0) == 1 && directions.shape(1) == 3);
    if (!uniform && (directions.ndim() != 2 || directions.shape(0) != n || directions.shape(1) != 3))
        throw py::value_error("Expected one direction or one direction per ray");
    if (limits.ndim() > 1 || (limits.size() != 1 && limits.size() != n))
        throw py::value_error("Expected one limit or one limit per ray");

    std::vector<RTCRayHit> rays(n);
    for (py::ssize_t i = 0; i < n; ++i) {
        const float* p = starts.data() + i * 3;
        const float* d = directions.data() + (uniform ? 0 : i * 3);
        auto& ray = rays[i].ray;
        ray.tfar = limits.data()[limits.size() == 1 ? 0 : i];
        if (!std::isfinite(ray.tfar) || ray.tfar < 0 ||
            !std::all_of(p, p + 3, [](float x) { return std::isfinite(x); }) ||
            !std::all_of(d, d + 3, [](float x) { return std::isfinite(x); }))
            throw py::value_error("Invalid ray segment");
        ray.org_x = p[0]; ray.org_y = p[1]; ray.org_z = p[2];
        ray.dir_x = d[0]; ray.dir_y = d[1]; ray.dir_z = d[2];
        ray.mask = channel;
    }
    py::array_t<std::int32_t> faces(n);
    py::array_t<float> distances(n), normals({n, py::ssize_t(3)});
    auto* face = faces.mutable_data();
    auto* distance = distances.mutable_data();
    auto* normal = normals.mutable_data();
    {
        py::gil_scoped_release release;
        scene.intersect(rays);
        for (const auto& item : rays) {
            *face++ = item.hit.geomID == RTC_INVALID_GEOMETRY_ID ? -1 : static_cast<std::int32_t>(item.hit.primID);
            *distance++ = item.ray.tfar;
            *normal++ = item.hit.Ng_x;
            *normal++ = item.hit.Ng_y;
            *normal++ = item.hit.Ng_z;
        }
    }
    return py::make_tuple(faces, distances, normals);
}
}

void bind_rays(py::module_& module) {
    module.attr("TRIANGLE_API_VERSION") = 1;
    py::class_<esport::TriangleScene>(module, "TriangleScene")
        .def(py::init(&make_scene), py::arg("vertices"), py::arg("faces"), py::arg("masks"))
        .def("first_many", &first_many, py::arg("starts"), py::arg("directions"),
             py::arg("limits"), py::arg("channel"));
}
