#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ywta/mesh_core/raw_topology.h"

namespace ywta::mesh_core {

/** 髪チューブのトポロジー抽出結果。 */
enum class HairTubeStatus {
  kOk = 0,
  kInvalidTopology,
  kNullRootVertices,
  kRootLoopCountNotFour,
  kRootVertexOutOfRange,
  kRepeatedRootVertex,
  kRootEdgeMissing,
  kRootNotBoundary,
  kNonQuadFace,
  kNonManifoldEdge,
  kWindingConflict,
  kAmbiguousContinuation,
  kSectionCountChanged,
  kRingRevisited,
  kDisconnectedTopology,
};

/** ユーザーが巡回順を指定したroot edge loop。 */
struct HairTubeRootLoopView {
  const std::uint32_t* vertices = nullptr;
  std::uint64_t count = 0;
};

/**
 * 4 railと共有ring列を保持する抽出結果。
 *
 * ringsはstation-major、railsはrail-majorで、それぞれ同じ頂点IDを保持する。
 * side_facesは各station区間についてrootのedge順に4面を保持する。
 */
struct HairTubeTopology {
  std::uint64_t station_count = 0;
  std::vector<std::uint32_t> rings;
  std::vector<std::uint32_t> rails;
  std::vector<std::uint64_t> side_faces;
};

/** 髪チューブ抽出の状態と診断。 */
struct HairTubeTopologyResult {
  HairTubeStatus status = HairTubeStatus::kOk;
  TopologyStatus topology_status = TopologyStatus::kOk;
  std::string message;
  HairTubeTopology topology;

  [[nodiscard]] bool ok() const noexcept { return status == HairTubeStatus::kOk; }
};

/**
 * 単一のopen quad tubeから4 railと共有ring列をread-onlyで抽出する。
 *
 * root_loopの巡回順をrail ID 0〜3の正本とする。cap、triangle、分岐、再訪、
 * non-manifold、余分なcomponentは修復せず、部分結果を返さず拒否する。
 */
[[nodiscard]] HairTubeTopologyResult extract_hair_tube_topology(
    const RawTopologyView& topology, const HairTubeRootLoopView& root_loop);

}  // namespace ywta::mesh_core
