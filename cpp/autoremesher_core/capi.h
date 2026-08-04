// ywta_autoremesher C ABI
//
// Blender 側は Python バージョンに依存しない ctypes 経由で利用するため、
// C++ の名前修飾を避けた素の C ABI として公開する。
// メモリ確保は本DLL内で行い、解放も必ず ywta_remesh_free() を通して行うこと
// （呼び出し側の delete / free で解放してはならない。CRTの境界を越えるため）。
#ifndef YWTA_AUTOREMESHER_CAPI_H
#define YWTA_AUTOREMESHER_CAPI_H

#include <stdint.h>

#if defined(_WIN32)
#if defined(YWTA_AUTOREMESHER_BUILD_DLL)
#define YWTA_AUTOREMESHER_API __declspec(dllexport)
#else
#define YWTA_AUTOREMESHER_API __declspec(dllimport)
#endif
#else
#define YWTA_AUTOREMESHER_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

// AutoRemesher::ModelType に対応（0 = Organic, 1 = HardSurface）
enum YwtaModelType {
    YWTA_MODEL_TYPE_ORGANIC = 0,
    YWTA_MODEL_TYPE_HARD_SURFACE = 1
};

typedef struct YwtaRemeshParams {
    uint64_t target_triangle_count; // 0 の場合はライブラリ既定値を使う
    double scaling; // 0.0以下の場合は既定値 1.0 を使う（AutoRemesherは0.0だと結果が退化する）
    double adaptivity;
    int model_type; // YwtaModelType
    double sharp_edge_degrees; // シャープエッジと判定する角度（度）。ライブラリ既定値は90.0
    double smooth_normal_degrees; // 法線を平滑化する角度（度）。ライブラリ既定値は0.0
} YwtaRemeshParams;

// 進捗コールバック。tag は ywta_remesh() に渡した値がそのまま渡る。
typedef void (*YwtaRemeshProgressCallback)(void* tag, float progress, const char* status);

// 戻り値:
//   0  成功
//   1  引数が不正（NULL / 頂点数0 / 三角形数0 など）
//   2  リメッシュ処理中に例外が発生した
//   3  AutoRemesher::remesh() が失敗を返した
//   4  結果が空だった
//   5  メモリ確保に失敗した
//
// vertices は [x0,y0,z0, x1,y1,z1, ...] の並びで vertex_count 個。
// tri_indices は入力メッシュの三角形インデックス（3つ組み） * tri_count。
// 出力面はクアッド・トライアングル混在の可能性があるため、
// out_face_indices（頂点インデックスの連結配列）と
// out_face_counts（各面の頂点数、通常3か4）の組で返す。
// 解放は ywta_remesh_free() でのみ行うこと。
YWTA_AUTOREMESHER_API int ywta_remesh(
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
    uint64_t* out_face_count);

// ywta_remesh() が確保した出力バッファを解放する。
// 各ポインタは NULL でもよい（NULL は無視する）。
YWTA_AUTOREMESHER_API void ywta_remesh_free(
    double* vertices,
    uint32_t* face_indices,
    uint32_t* face_counts);

#ifdef __cplusplus
}
#endif

#endif // YWTA_AUTOREMESHER_CAPI_H
