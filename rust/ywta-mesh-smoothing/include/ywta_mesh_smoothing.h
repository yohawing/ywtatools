#ifndef YWTA_MESH_SMOOTHING_H
#define YWTA_MESH_SMOOTHING_H

/* Maya/Blenderから共有する均一ラプラシアン参照実装のC ABI。 */

#include <stdint.h>

#if defined(_WIN32)
#define YWTA_MESH_SMOOTHING_API __declspec(dllimport)
#else
#define YWTA_MESH_SMOOTHING_API
#endif

#define YWTA_MESH_SMOOTHING_ABI_VERSION UINT32_C(1)
#define YWTA_MESH_SMOOTHING_MODE_UNIFORM_LAPLACIAN UINT32_C(0)

/* 成功およびエラーコード。 */
#define YWTA_MESH_SMOOTHING_STATUS_OK INT32_C(0)
#define YWTA_MESH_SMOOTHING_STATUS_INVALID_ARGUMENT INT32_C(1)
#define YWTA_MESH_SMOOTHING_STATUS_ABI_MISMATCH INT32_C(2)
#define YWTA_MESH_SMOOTHING_STATUS_NULL_POINTER INT32_C(3)
#define YWTA_MESH_SMOOTHING_STATUS_LENGTH_OVERFLOW INT32_C(4)
#define YWTA_MESH_SMOOTHING_STATUS_OUTPUT_TOO_SMALL INT32_C(5)
#define YWTA_MESH_SMOOTHING_STATUS_EDGE_INDEX_OUT_OF_RANGE INT32_C(6)
#define YWTA_MESH_SMOOTHING_STATUS_NON_FINITE INT32_C(7)
#define YWTA_MESH_SMOOTHING_STATUS_OVERLAPPING_BUFFERS INT32_C(8)
#define YWTA_MESH_SMOOTHING_STATUS_UNSUPPORTED_MODE INT32_C(9)
#define YWTA_MESH_SMOOTHING_STATUS_PANIC INT32_C(10)

typedef struct ywta_mesh_smoothing_options {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t mode;
    uint32_t iterations;
    double strength;
} ywta_mesh_smoothing_options;

typedef struct ywta_mesh_smoothing_request {
    uint32_t abi_version;
    uint32_t struct_size;
    const double *positions;
    uint64_t position_count;
    const uint32_t *edges;
    uint64_t edge_count;
    double *output;
    uint64_t output_len;
    const ywta_mesh_smoothing_options *options;
} ywta_mesh_smoothing_request;

#ifdef __cplusplus
extern "C" {
#endif

/*
 * positions は position_count * 3 個の有限なdouble、edges は edge_count * 2 個の
 * 頂点インデックス。output は呼び出し側が output_len 個以上を確保し、入力バッファ
 * と重ならないようにする。ポインタは呼び出し中だけ有効で、DLLは所有・保持しない。
 * positions/edges は要素数が0ならNULLを許可するが、非0ならNULL不可かつ自然アライメント
 * が必要。outputもoutput_lenが非0ならNULL不可で自然アライメントが必要（0ならNULL可）。
 * options/requestはNULL不可で、abi_version=1、struct_sizeは現在の構造体以上。
 * strength は [0,1] の有限値、iterations は1以上、modeは0のみ有効。
 * 成功時も出力の解放は呼び出し側が行う。戻り値は上記STATUS_*のいずれか。
 */
YWTA_MESH_SMOOTHING_API int32_t ywta_mesh_smoothing_apply(
    const ywta_mesh_smoothing_request *request);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* YWTA_MESH_SMOOTHING_H */
