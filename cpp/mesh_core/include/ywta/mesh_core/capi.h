#pragma once

#include <stdint.h>

#if defined(_WIN32) && defined(YWTA_MESH_CORE_EXPORTS)
#define YWTA_MESH_CORE_API __declspec(dllexport)
#elif defined(_WIN32)
#define YWTA_MESH_CORE_API __declspec(dllimport)
#else
#define YWTA_MESH_CORE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/** C ABIが所有する髪チューブ再生成結果。 */
typedef struct YwtaHairTubeOutput {
  uint64_t vertex_count;
  uint64_t quad_count;
  double* positions_xyz;
  uint32_t* quad_indices;
  uint64_t* source_intervals;
  double* source_alphas;
  uint32_t* source_vertex_pairs;
  uint64_t* source_faces;
  uint64_t* source_corner_faces;
  uint64_t source_station_count;
  double max_fit_deviation;
  double max_source_distance;
  int cubic_active;
  int root_capped;
  int tip_capped;
  uint64_t rail_count;
} YwtaHairTubeOutput;

/** C ABIが所有するread-only mesh診断結果。 */
typedef struct YwtaMeshDiagnosticOutput {
  uint64_t zero_area_face_count;
  uint64_t* zero_area_faces;
  uint64_t duplicate_face_count;
  uint64_t* duplicate_faces;
  uint64_t non_manifold_edge_count;
  uint32_t* non_manifold_edges;
  uint64_t winding_conflict_edge_count;
  uint32_t* winding_conflict_edges;
  uint64_t bow_tie_vertex_count;
  uint32_t* bow_tie_vertices;
  uint64_t boundary_loop_count;
  uint64_t* boundary_loop_offsets;
  uint32_t* boundary_loop_vertices;
} YwtaMeshDiagnosticOutput;

/**
 * flat topologyと4頂点root loopから固定密度のopen quad tubeを生成する。
 *
 * positions_xyzはvertex_count*3、face_offsetsはface_count+1、root_verticesは4要素。
 * 成功後は必ずywta_hair_tube_free()を呼ぶ。成功は0、失敗は0以外。
 */
YWTA_MESH_CORE_API int ywta_hair_tube_generate(uint32_t vertex_count, const double* positions_xyz,
                                               const uint64_t* face_offsets, uint64_t face_count,
                                               const uint32_t* face_vertices,
                                               uint64_t face_vertex_count,
                                               const uint32_t* root_vertices,
                                               uint64_t target_segments, double fit_tolerance,
                                               YwtaHairTubeOutput* output);

/** flat topologyと3頂点以上のroot loopから固定密度tubeを生成する。 */
YWTA_MESH_CORE_API int ywta_hair_tube_generate_n(
    uint32_t vertex_count, const double* positions_xyz, const uint64_t* face_offsets,
    uint64_t face_count, const uint32_t* face_vertices, uint64_t face_vertex_count,
    const uint32_t* root_vertices, uint64_t root_count, uint64_t target_segments,
    double fit_tolerance, YwtaHairTubeOutput* output);

/** rail-majorな4本の編集済みpoint列から固定密度tubeを再生成する。 */
YWTA_MESH_CORE_API int ywta_hair_tube_generate_from_rails(const double* rail_positions_xyz,
                                                          uint64_t station_count,
                                                          uint64_t target_segments,
                                                          double fit_tolerance,
                                                          YwtaHairTubeOutput* output);

/** rail-majorな4本の編集済みpoint列からcap指定付きで固定密度tubeを再生成する。 */
YWTA_MESH_CORE_API int ywta_hair_tube_generate_from_rails_ex(const double* rail_positions_xyz,
                                                             uint64_t station_count,
                                                             uint64_t target_segments,
                                                             double fit_tolerance, int root_capped,
                                                             int tip_capped,
                                                             YwtaHairTubeOutput* output);

/** rail-majorな可変本数の編集済みpoint列から固定密度tubeを再生成する。 */
YWTA_MESH_CORE_API int ywta_hair_tube_generate_from_rails_n(
    const double* rail_positions_xyz, uint64_t rail_count, uint64_t station_count,
    uint64_t target_segments, double fit_tolerance, int root_capped, int tip_capped,
    YwtaHairTubeOutput* output);

/** ywta_hair_tube_generate()が確保した配列を解放し、outputをゼロ初期化する。 */
YWTA_MESH_CORE_API void ywta_hair_tube_free(YwtaHairTubeOutput* output);

/** flat topologyを変更せず診断し、該当要素IDを返す。 */
YWTA_MESH_CORE_API int ywta_mesh_diagnose(
    uint32_t vertex_count, const double* positions_xyz, const uint64_t* face_offsets,
    uint64_t face_count, const uint32_t* face_vertices, uint64_t face_vertex_count,
    double area_epsilon, YwtaMeshDiagnosticOutput* output);

/** ywta_mesh_diagnose()が確保した配列を解放し、outputをゼロ初期化する。 */
YWTA_MESH_CORE_API void ywta_mesh_diagnostic_free(YwtaMeshDiagnosticOutput* output);

/** 現在のthreadで最後に発生したエラー説明。次のAPI呼び出しまで有効。 */
YWTA_MESH_CORE_API const char* ywta_mesh_core_last_error(void);

#ifdef __cplusplus
}
#endif
