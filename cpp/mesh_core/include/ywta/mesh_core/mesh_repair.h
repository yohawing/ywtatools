#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ywta/mesh_core/mesh_diagnostics.h"

namespace ywta::mesh_core {

inline constexpr std::uint64_t kRemovedFace = UINT64_MAX;

/** 安全修復planの状態。 */
enum class MeshRepairStatus {
  kOk = 0,
  kInvalidInput,
  kUnsafeNonManifoldEdge,
  kNonOrientableSurface,
};

/** 入力を変更せず作るface削除・反転plan。 */
struct MeshRepairPlan {
  std::vector<std::uint64_t> face_offsets;
  std::vector<std::uint32_t> face_vertices;
  std::vector<std::uint64_t> old_face_to_new;
  std::vector<std::uint64_t> source_face_by_output;
  std::vector<std::uint64_t> source_corner_by_output;
  std::vector<std::uint64_t> removed_zero_area_faces;
  std::vector<std::uint64_t> removed_duplicate_faces;
  std::vector<std::uint64_t> flipped_source_faces;
};

/** 修復planとfail-closed診断。 */
struct MeshRepairResult {
  MeshRepairStatus status = MeshRepairStatus::kOk;
  MeshDiagnosticStatus diagnostic_status = MeshDiagnosticStatus::kOk;
  TopologyStatus topology_status = TopologyStatus::kOk;
  std::string message;
  MeshRepairPlan plan;

  [[nodiscard]] bool ok() const noexcept { return status == MeshRepairStatus::kOk; }
};

/** zero-area・後発duplicate faceを除去し、manifold face windingを整合させるdry-run plan。 */
[[nodiscard]] MeshRepairResult plan_safe_mesh_repair(const RawTopologyView& topology,
                                                     const Point3dView& positions,
                                                     double area_epsilon = 1.0e-12);

}  // namespace ywta::mesh_core
