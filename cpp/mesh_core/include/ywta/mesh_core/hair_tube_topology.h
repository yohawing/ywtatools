#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "ywta/mesh_core/raw_topology.h"

namespace ywta::mesh_core {

inline constexpr std::uint64_t kNoHairTubeFace = UINT64_MAX;

/** 髪チューブのトポロジー抽出結果。 */
enum class HairTubeStatus {
  kOk = 0,
  kInvalidTopology,
  kNullRootVertices,
  kInvalidRootLoopCount,
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
 * 3本以上のrailと共有ring列を保持する抽出結果。
 *
 * ringsはstation-major、railsはrail-majorで、それぞれ同じ頂点IDを保持する。
 * side_facesは各station区間についてrootのedge順にrail_count面を保持する。
 */
struct HairTubeTopology {
  std::uint64_t rail_count = 0;
  std::uint64_t station_count = 0;
  std::vector<std::uint32_t> rings;
  std::vector<std::uint32_t> rails;
  std::vector<std::uint64_t> side_faces;
  std::uint64_t root_cap_face = kNoHairTubeFace;
  std::uint64_t tip_cap_face = kNoHairTubeFace;
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
 * root_loopの巡回順をrail IDの正本とする。4-sided入力のroot/tip quad capは保持する。
 * triangle、分岐、再訪、non-manifold、余分なcomponentは修復せず、部分結果を返さず拒否する。
 */
[[nodiscard]] HairTubeTopologyResult extract_hair_tube_topology(
    const RawTopologyView& topology, const HairTubeRootLoopView& root_loop);

}  // namespace ywta::mesh_core
