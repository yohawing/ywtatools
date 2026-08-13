// ywta_autoremesher C ABI 実装
//
// AutoRemesher::AutoRemesher（external/autoremesher/src/AutoRemesher/autoremesher.h）
// をメモリ上の頂点/三角形配列でラップする。ABI境界を越える例外は存在しないため、
// C++ 例外は全てここで捕捉してエラーコードに変換する。
#include "capi.h"
#include "quiet_output.h"

#include <AutoRemesher/AutoRemesher>
#include <AutoRemesher/Vector3>
#include <geogram/basic/common.h>

#include <exception>
#include <mutex>
#include <new>
#include <vector>

namespace {

// Geogram はプロセス中で一度だけ GEO::initialize() を呼ぶ必要がある
// （src/main.cpp の起動時呼び出しに相当。呼ばないと述語計算の初期化前アクセス等で
// クラッシュする）。DLLは複数回 ywta_remesh() が呼ばれるため一度だけ初期化する。
void ensureGeogramInitialized()
{
    static std::once_flag initialized;
    std::call_once(initialized, []() {
        GEO::initialize(GEO::GEOGRAM_INSTALL_HANDLERS);
    });
}

// 出力バッファの確保に失敗した場合、それまでに確保した分を片付けるための
// 小さなRAIIヘルパー。成功時は release() で解放責務を呼び出し側に渡す。
template <typename T>
class ScopedArray {
public:
    explicit ScopedArray(T* ptr = nullptr)
        : m_ptr(ptr)
    {
    }
    ~ScopedArray()
    {
        delete[] m_ptr;
    }
    T* get() const { return m_ptr; }
    T* release()
    {
        T* p = m_ptr;
        m_ptr = nullptr;
        return p;
    }

private:
    T* m_ptr;
};

} // namespace

int ywta_remesh(
    const double* vertices,
    uint64_t vertex_count,
    const uint32_t* tri_indices,
    uint64_t tri_count,
    const YwtaRemeshParams* params,
    YwtaRemeshProgressCallback progress_cb,
    void* tag,
    double** out_vertices,
    uint64_t* out_vertex_count,
    uint32_t** out_face_indices,
    uint32_t** out_face_counts,
    uint64_t* out_face_count)
{
    if (nullptr == out_vertices || nullptr == out_vertex_count
        || nullptr == out_face_indices || nullptr == out_face_counts
        || nullptr == out_face_count) {
        return 1;
    }

    *out_vertices = nullptr;
    *out_vertex_count = 0;
    *out_face_indices = nullptr;
    *out_face_counts = nullptr;
    *out_face_count = 0;

    if (nullptr == vertices || 0 == vertex_count
        || nullptr == tri_indices || 0 == tri_count
        || nullptr == params) {
        return 1;
    }

    try {
        ensureGeogramInitialized();
        ywta::autoremesher::ScopedQuietOutput quietOutput;

        std::vector<AutoRemesher::Vector3> inputVertices;
        inputVertices.reserve((size_t)vertex_count);
        for (uint64_t i = 0; i < vertex_count; ++i) {
            inputVertices.push_back(AutoRemesher::Vector3(
                vertices[i * 3 + 0],
                vertices[i * 3 + 1],
                vertices[i * 3 + 2]));
        }

        std::vector<std::vector<size_t>> inputTriangles;
        inputTriangles.reserve((size_t)tri_count);
        for (uint64_t i = 0; i < tri_count; ++i) {
            std::vector<size_t> triangle;
            triangle.reserve(3);
            triangle.push_back((size_t)tri_indices[i * 3 + 0]);
            triangle.push_back((size_t)tri_indices[i * 3 + 1]);
            triangle.push_back((size_t)tri_indices[i * 3 + 2]);
            inputTriangles.push_back(std::move(triangle));
        }

        AutoRemesher::AutoRemesher autoRemesher(inputVertices, inputTriangles);

        if (params->target_triangle_count > 0)
            autoRemesher.setTargetTriangleCount((size_t)params->target_triangle_count);
        // AutoRemesher::m_scaling の既定値は 0.0 だが、それをそのまま
        // GEO::GlobalParam2d::quad_cover() に渡すと結果が退化する
        // （本家GUIの既定値は 1.0 -- src/mainwindow.h の m_targetScaling を参照）。
        autoRemesher.setScaling(params->scaling > 0.0 ? params->scaling : 1.0);
        if (params->adaptivity > 0.0)
            autoRemesher.setGradientAdaptivity(params->adaptivity);
        autoRemesher.setModelType(
            YWTA_MODEL_TYPE_HARD_SURFACE == params->model_type
                ? AutoRemesher::ModelType::HardSurface
                : AutoRemesher::ModelType::Organic);
        // シャープエッジ/法線平滑化の角度（度）。呼び出し側（Python/Maya）が
        // ライブラリ既定値（90.0 / 0.0）を明示的に渡す前提で常に設定する。
        autoRemesher.setSharpEdgeDegrees(params->sharp_edge_degrees);
        autoRemesher.setSmoothNormalDegrees(params->smooth_normal_degrees);
        if (nullptr != progress_cb) {
            autoRemesher.setTag(tag);
            autoRemesher.setProgressHandler(progress_cb);
        }

        bool ok = autoRemesher.remesh();
        if (!ok)
            return 3;

        const std::vector<AutoRemesher::Vector3>& remeshedVertices = autoRemesher.remeshedVertices();
        const std::vector<std::vector<size_t>>& remeshedFaces = autoRemesher.remeshedQuads();

        if (remeshedVertices.empty() || remeshedFaces.empty())
            return 4;

        uint64_t vertexResultCount = (uint64_t)remeshedVertices.size();
        ScopedArray<double> vertexBuffer(new (std::nothrow) double[(size_t)vertexResultCount * 3]);
        if (nullptr == vertexBuffer.get())
            return 5;
        for (uint64_t i = 0; i < vertexResultCount; ++i) {
            const AutoRemesher::Vector3& v = remeshedVertices[(size_t)i];
            vertexBuffer.get()[i * 3 + 0] = v.x();
            vertexBuffer.get()[i * 3 + 1] = v.y();
            vertexBuffer.get()[i * 3 + 2] = v.z();
        }

        uint64_t faceResultCount = (uint64_t)remeshedFaces.size();
        ScopedArray<uint32_t> faceCountsBuffer(new (std::nothrow) uint32_t[(size_t)faceResultCount]);
        if (nullptr == faceCountsBuffer.get())
            return 5;

        uint64_t totalIndexCount = 0;
        for (uint64_t i = 0; i < faceResultCount; ++i) {
            uint32_t n = (uint32_t)remeshedFaces[(size_t)i].size();
            faceCountsBuffer.get()[i] = n;
            totalIndexCount += n;
        }

        ScopedArray<uint32_t> faceIndicesBuffer(new (std::nothrow) uint32_t[(size_t)totalIndexCount]);
        if (nullptr == faceIndicesBuffer.get())
            return 5;

        uint64_t cursor = 0;
        for (uint64_t i = 0; i < faceResultCount; ++i) {
            const std::vector<size_t>& face = remeshedFaces[(size_t)i];
            for (size_t vertexIndex : face) {
                faceIndicesBuffer.get()[cursor++] = (uint32_t)vertexIndex;
            }
        }

        *out_vertices = vertexBuffer.release();
        *out_vertex_count = vertexResultCount;
        *out_face_indices = faceIndicesBuffer.release();
        *out_face_counts = faceCountsBuffer.release();
        *out_face_count = faceResultCount;

        return 0;
    } catch (const std::bad_alloc&) {
        return 5;
    } catch (const std::exception&) {
        return 2;
    } catch (...) {
        return 2;
    }
}

void ywta_remesh_free(
    double* vertices,
    uint32_t* face_indices,
    uint32_t* face_counts)
{
    delete[] vertices;
    delete[] face_indices;
    delete[] face_counts;
}
