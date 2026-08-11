#ifndef YWTA_MESH_SMOOTHING_H
#define YWTA_MESH_SMOOTHING_H

/* Maya/Blenderから共有するメッシュスムージングC ABI。 */

#include <stdint.h>

#if defined(_WIN32)
#define YWTA_MESH_SMOOTHING_API __declspec(dllimport)
#else
#define YWTA_MESH_SMOOTHING_API
#endif

#define YWTA_MESH_SMOOTHING_ABI_VERSION UINT32_C(1)
#define YWTA_MESH_SMOOTHING_MODE_UNIFORM_LAPLACIAN UINT32_C(0)
#define YWTA_MESH_SMOOTHING_MODE_TAUBIN UINT32_C(1)
#define YWTA_MESH_SMOOTHING_MODE_HC UINT32_C(2)
#define YWTA_MESH_SMOOTHING_OPTIONS_V1_SIZE UINT32_C(24)
#define YWTA_MESH_SMOOTHING_OPTIONS_TAUBIN_SIZE UINT32_C(32)
#define YWTA_MESH_SMOOTHING_OPTIONS_HC_SIZE UINT32_C(48)
#define YWTA_MESH_SMOOTHING_OPTIONS_VOLUME_SIZE UINT32_C(56)
#define YWTA_MESH_SMOOTHING_REQUEST_V1_SIZE UINT32_C(64)
#define YWTA_MESH_SMOOTHING_REQUEST_CONSTRAINTS_SIZE UINT32_C(88)
#define YWTA_MESH_SMOOTHING_REQUEST_TRIANGLES_SIZE UINT32_C(104)

#define YWTA_MESH_SMOOTHING_CONSTRAINT_FREE UINT32_C(0)
#define YWTA_MESH_SMOOTHING_CONSTRAINT_FIXED UINT32_C(1)
#define YWTA_MESH_SMOOTHING_CONSTRAINT_SURFACE_PLANE UINT32_C(2)
#define YWTA_MESH_SMOOTHING_CONSTRAINT_RAIL_LINE UINT32_C(3)
#define YWTA_MESH_SMOOTHING_CONSTRAINT_NORMAL_ONLY UINT32_C(4)

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
#define YWTA_MESH_SMOOTHING_STATUS_INVALID_CONSTRAINT INT32_C(11)
#define YWTA_MESH_SMOOTHING_STATUS_INVALID_TOPOLOGY INT32_C(12)
#define YWTA_MESH_SMOOTHING_STATUS_VOLUME_CORRECTION_FAILED INT32_C(13)

typedef struct ywta_mesh_smoothing_options {
    uint32_t abi_version;
    uint32_t struct_size;
    uint32_t mode;
    uint32_t iterations;
    double strength;
    double taubin_mu;
    double hc_alpha;
    double hc_beta;
    double volume_correction;
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
    const double *vertex_weights;
    const uint32_t *constraint_modes;
    const double *constraint_directions;
    const uint32_t *triangles;
    uint64_t triangle_count;
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
 * options/requestはNULL不可で、abi_version=1。Uniformモードは旧V1の24 bytes
 * optionsを引き続き受理する。Taubinモードは32 bytes以上、HCモードは48 bytes以上を
 * 必要とする。
 * strength は [0,1] の有限値、iterations は1以上。Taubinではstrengthをλ、
 * taubin_muをμとして使い、0 < λ < -μ <= 1を要求する。
 * HCではstrengthをLaplacian前進係数、hc_alphaを元位置の参照率、hc_betaを
 * 自頂点の補正率として使い、いずれも[0,1]を要求する。
 * 56 bytes版optionsのvolume_correctionは[0,1]。0より大きい場合は104 bytes版
 * requestのtrianglesをtriangle_count個渡す。三角形は閉じた2-manifoldで辺方向が
 * 整合している必要がある。補正は初期符号付き体積を目標に体積勾配方向へ移動する。
 * requestの旧V1 64 bytesも受理する。88 bytes版ではvertex_weights（頂点ごとの
 * [0,1]）とconstraint_modesを省略可能。方向を使うモードでは
 * constraint_directionsに正規化前のxyzを頂点数分渡す。SurfacePlaneは方向の
 * 直交平面、RailLine/NormalOnlyは方向軸へ変位を射影する。各入力は呼び出し中だけ
 * 参照し、outputと重ならないこと。
 * 成功時も出力の解放は呼び出し側が行う。戻り値は上記STATUS_*のいずれか。
 */
YWTA_MESH_SMOOTHING_API int32_t ywta_mesh_smoothing_apply(
    const ywta_mesh_smoothing_request *request);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* YWTA_MESH_SMOOTHING_H */
