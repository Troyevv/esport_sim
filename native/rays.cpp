#include "rays.hpp"

#include "rtcore_geometry.h"
#include "rtcore_scene.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace esport {
namespace {
// The Python wheel has platform-specific library names. Open the exact library
// already loaded by embreex. TBB can finish worker teardown after C++ static
// destructors run, so its code must remain mapped until process termination.
class Library {
public:
    explicit Library(const std::filesystem::path& path) {
        if (!path.is_absolute()) throw std::invalid_argument("Expected an absolute Embree path");
#ifdef _WIN32
        handle_ = LoadLibraryExW(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        HMODULE pinned{};
        if (handle_ && !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN, path.c_str(), &pinned)) {
            FreeLibrary(handle_);
            throw std::runtime_error("Could not pin the installed Embree runtime");
        }
#else
        handle_ = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL | RTLD_NODELETE);
#endif
        if (!handle_) throw std::runtime_error("Could not load the installed Embree 4 library");
    }
    ~Library() {
#ifdef _WIN32
        FreeLibrary(handle_);
#else
        dlclose(handle_);
#endif
    }
    Library(const Library&) = delete;
    Library& operator=(const Library&) = delete;

    template<class F> F symbol(const char* name) const {
#ifdef _WIN32
        auto address = GetProcAddress(handle_, name);
#else
        auto address = dlsym(handle_, name);
#endif
        if (!address) throw std::runtime_error(std::string("Missing Embree function ") + name);
        return reinterpret_cast<F>(address);
    }

private:
#ifdef _WIN32
    HMODULE handle_;
#else
    void* handle_;
#endif
};

struct Api {
    Library library;
    explicit Api(const std::filesystem::path& path) : library(path) {}
#define LOAD_RTC(name) decltype(&::name) name = library.symbol<decltype(&::name)>(#name)
    LOAD_RTC(rtcNewDevice);
    LOAD_RTC(rtcGetDeviceProperty);
    LOAD_RTC(rtcGetDeviceError);
    LOAD_RTC(rtcReleaseDevice);
    LOAD_RTC(rtcNewScene);
    LOAD_RTC(rtcSetSceneFlags);
    LOAD_RTC(rtcCommitScene);
    LOAD_RTC(rtcReleaseScene);
    LOAD_RTC(rtcNewGeometry);
    LOAD_RTC(rtcSetGeometryMask);
    LOAD_RTC(rtcSetSharedGeometryBuffer);
    LOAD_RTC(rtcSetNewGeometryBuffer);
    LOAD_RTC(rtcCommitGeometry);
    LOAD_RTC(rtcAttachGeometry);
    LOAD_RTC(rtcReleaseGeometry);
    LOAD_RTC(rtcIntersect1);
#undef LOAD_RTC
};

const Api& installed_api(const std::filesystem::path& path) {
    // Embree's TBB workers outlive an individual scene. Keep the library
    // loaded across map changes, as embreex.rtcore does in the game process.
    static const Api api(path);
    return api;
}

template<class Handle, class Release>
auto owned(Handle handle, Release release) {
    if (!handle) throw std::runtime_error("Embree could not allocate a handle");
    return std::unique_ptr<std::remove_pointer_t<Handle>, Release>(handle, release);
}
}

class TriangleScene::Impl {
public:
    const Api& api;
    // Embree reads a 16-byte SIMD word at the final 12-byte vertex.
    std::vector<Vertex> vertices;
    std::vector<std::uint32_t> face_ids, offsets;
    std::unique_ptr<RTCSceneTy, decltype(&::rtcReleaseScene)> scene;

    Impl(const std::filesystem::path& path, std::vector<Vertex> source,
         const std::vector<Face>& faces, const std::vector<std::uint8_t>& masks)
        : api(installed_api(path)), vertices(std::move(source)), scene(nullptr, api.rtcReleaseScene) {
        if (faces.size() != masks.size() || faces.size() > std::numeric_limits<std::int32_t>::max())
            throw std::invalid_argument("Invalid face or mask count");
        for (const auto& vertex : vertices) {
            for (float value : vertex)
                if (!std::isfinite(value)) throw std::invalid_argument("Non-finite collision vertex");
        }
        for (const auto& face : faces) {
            for (auto index : face)
                if (index < 0 || static_cast<std::size_t>(index) >= vertices.size())
                    throw std::invalid_argument("Face references a missing collision vertex");
        }
        const auto count = vertices.size();
        vertices.emplace_back();
        auto device = owned(api.rtcNewDevice("isa=sse2,threads=1"), api.rtcReleaseDevice);
        if (api.rtcGetDeviceProperty(device.get(), RTC_DEVICE_PROPERTY_VERSION) != RTC_VERSION)
            throw std::runtime_error("Incompatible Embree runtime version");
        scene = owned(api.rtcNewScene(device.get()), api.rtcReleaseScene);
        api.rtcSetSceneFlags(scene.get(), RTC_SCENE_FLAG_ROBUST);

        // Stable counting sort by the channel mask. Input order within each
        // group is observable at coplanar surfaces and portal boundaries.
        std::array<std::uint32_t, 257> starts{};
        for (auto mask : masks) ++starts[mask + 1];
        std::partial_sum(starts.begin(), starts.end(), starts.begin());
        auto next = starts;
        face_ids.resize(faces.size());
        for (std::uint32_t i = 0; i < faces.size(); ++i) face_ids[next[masks[i]]++] = i;
        for (unsigned mask = 1; mask < 256; ++mask) {
            auto first = starts[mask], last = starts[mask + 1];
            if (first == last) continue;
            auto mesh = owned(api.rtcNewGeometry(device.get(), RTC_GEOMETRY_TYPE_TRIANGLE), api.rtcReleaseGeometry);
            api.rtcSetGeometryMask(mesh.get(), mask);
            api.rtcSetSharedGeometryBuffer(mesh.get(), RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3,
                                           vertices.data(), 0, sizeof(Vertex), count);
            auto* indices = static_cast<std::uint32_t*>(api.rtcSetNewGeometryBuffer(
                mesh.get(), RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3, 3 * sizeof(std::uint32_t), last - first));
            if (!indices) throw std::bad_alloc();
            for (auto i = first; i < last; ++i) {
                const auto& face = faces[face_ids[i]];
                indices = std::copy(face.begin(), face.end(), indices);
            }
            api.rtcCommitGeometry(mesh.get());
            auto id = api.rtcAttachGeometry(scene.get(), mesh.get());
            if (id != offsets.size()) throw std::runtime_error("Unexpected Embree geometry ID");
            offsets.push_back(first);
        }
        api.rtcCommitScene(scene.get());
        if (api.rtcGetDeviceError(device.get()) != RTC_ERROR_NONE)
            throw std::runtime_error("Embree failed to build the triangle scene");
    }
};

TriangleScene::TriangleScene(const std::filesystem::path& library, std::vector<Vertex> vertices,
                             const std::vector<Face>& faces, const std::vector<std::uint8_t>& masks)
    : impl_(std::make_unique<Impl>(library, std::move(vertices), faces, masks)) {}
TriangleScene::~TriangleScene() = default;

void TriangleScene::intersect(std::span<RTCRayHit> rays) const {
    for (auto& item : rays) {
        item.hit.geomID = item.hit.primID = RTC_INVALID_GEOMETRY_ID;
        std::fill(std::begin(item.hit.instID), std::end(item.hit.instID), RTC_INVALID_GEOMETRY_ID);
        impl_->api.rtcIntersect1(impl_->scene.get(), &item, nullptr);
        if (item.hit.geomID != RTC_INVALID_GEOMETRY_ID)
            item.hit.primID = impl_->face_ids.at(impl_->offsets.at(item.hit.geomID) + item.hit.primID);
    }
}
}
