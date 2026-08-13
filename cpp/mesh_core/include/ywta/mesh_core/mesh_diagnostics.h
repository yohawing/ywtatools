#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ywta/mesh_core/hair_tube_cage.h"
#include "ywta/mesh_core/raw_topology.h"

namespace ywta::mesh_core {

/** mesh診断の入力状態。 */
enum class MeshDiagnosticStatus {
  kOk = 0,
  kInvalidTopology,
  kNullPositions,
  kPositionCountMismatch,
  kNonFinitePosition,
  kInvalidAreaEpsilon,
};

/** 診断結果。edgeは2頂点、boundary loopはCSR形式で保持する。 */
struct MeshDiagnosticReport {
  std::vector<std::uint64_t> zero_area_faces;
  std::vector<std::uint64_t> duplicate_faces;
  std::vector<std::uint32_t> non_manifold_edges;
  std::vector<std::uint32_t> winding_conflict_edges;
  std::vector<std::uint32_t> bow_tie_vertices;
  std::vector<std::uint64_t> boundary_loop_offsets;
  std::vector<std::uint32_t> boundary_loop_vertices;
};

/** 診断状態とfail-closedな結果。 */
struct MeshDiagnosticResult {
  MeshDiagnosticStatus status = MeshDiagnosticStatus::kOk;
  TopologyStatus topology_status = TopologyStatus::kOk;
  std::string message;
  MeshDiagnosticReport report;

  [[nodiscard]] bool ok() const noexcept { return status == MeshDiagnosticStatus::kOk; }
};

/** topologyを変更せず、代表的な不正要素とboundary loopを決定的順序で分類する。 */
[[nodiscard]] MeshDiagnosticResult diagnose_mesh(const RawTopologyView& topology,
                                                 const Point3dView& positions,
                                                 double area_epsilon = 1.0e-12);

}  // namespace ywta::mesh_core
