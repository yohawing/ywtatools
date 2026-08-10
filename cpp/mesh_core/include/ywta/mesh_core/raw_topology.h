#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace ywta::mesh_core {

/** 入力トポロジーの検証または修復計画の状態。 */
enum class TopologyStatus {
  kOk = 0,
  kNullFaceOffsets,
  kNullFaceVertices,
  kInvalidFaceOffsets,
  kFaceTooSmall,
  kRepeatedFaceVertex,
  kVertexIndexOutOfRange,
  kOutputVertexOverflow,
};

/**
 * DCC の配列を所有せず参照する生トポロジー。
 *
 * face_offsets は face_count + 1 要素を持ち、最後の値は
 * face_vertex_count と一致しなければならない。
 */
struct RawTopologyView {
  std::uint32_t vertex_count = 0;
  const std::uint64_t* face_offsets = nullptr;
  std::uint64_t face_count = 0;
  const std::uint32_t* face_vertices = nullptr;
  std::uint64_t face_vertex_count = 0;
};

/** bow-tie 頂点一つに対して生成される頂点ID。 */
struct BowTieVertexSplit {
  std::uint32_t source_vertex = 0;
  std::vector<std::uint32_t> output_vertices;
};

/**
 * 入力を変更せず作成される bow-tie 頂点分離計画。
 *
 * rewritten_face_vertices は入力と同じface/corner順を保つ。
 * source_vertex_by_output を使うと、位置や頂点属性を元頂点からコピーできる。
 * source_to_output_* は旧頂点から新頂点群へのCSR形式の対応表である。
 */
struct BowTieSplitPlan {
  std::uint32_t original_vertex_count = 0;
  std::uint64_t output_vertex_count = 0;
  std::vector<std::uint32_t> rewritten_face_vertices;
  std::vector<std::uint32_t> source_vertex_by_output;
  std::vector<std::uint64_t> source_to_output_offsets;
  std::vector<std::uint32_t> source_to_output_vertices;
  std::vector<BowTieVertexSplit> splits;
};

/** bow-tie 頂点分離計画の作成結果。 */
struct BowTieSplitResult {
  TopologyStatus status = TopologyStatus::kOk;
  std::string message;
  BowTieSplitPlan plan;

  [[nodiscard]] bool ok() const noexcept { return status == TopologyStatus::kOk; }
};

/** 削除された要素を旧→新mappingで表す値。 */
inline constexpr std::uint64_t kRemovedElement = UINT64_MAX;

/**
 * edge-connected shellが三角形1面だけの場合に、その面を除外する計画。
 *
 * retained_face_* は新しいface/corner配列である。source_face_by_outputと
 * source_corner_by_outputを使うとface/corner属性を入力からコピーできる。
 * source_vertex_by_outputを使うと頂点属性をコピーできる。旧→新mappingの
 * 削除要素にはkRemovedElementが入る。
 */
struct SingleTriangleShellRemovalPlan {
  std::uint32_t original_vertex_count = 0;
  std::uint64_t output_vertex_count = 0;
  std::uint64_t original_face_count = 0;
  std::uint64_t output_face_count = 0;
  std::vector<std::uint64_t> retained_face_offsets;
  std::vector<std::uint32_t> retained_face_vertices;
  std::vector<std::uint64_t> source_face_by_output;
  std::vector<std::uint64_t> output_face_by_source;
  std::vector<std::uint64_t> source_corner_by_output;
  std::vector<std::uint32_t> source_vertex_by_output;
  std::vector<std::uint64_t> output_vertex_by_source;
  std::vector<std::uint64_t> removed_source_faces;
};

/** 1 triangle shell削除計画の作成結果。 */
struct SingleTriangleShellRemovalResult {
  TopologyStatus status = TopologyStatus::kOk;
  std::string message;
  SingleTriangleShellRemovalPlan plan;

  [[nodiscard]] bool ok() const noexcept { return status == TopologyStatus::kOk; }
};

/**
 * 頂点周りのface fanを共有edgeで連結し、複数fanを持つ頂点の分離計画を作る。
 *
 * 頂点位置やface数は変更しない。構造的に不正な入力は部分結果を返さず拒否する。
 */
[[nodiscard]] BowTieSplitResult plan_bow_tie_vertex_splits(const RawTopologyView& topology);

/**
 * 1 triangleだけで構成されたedge-connected shellを除外する計画を作る。
 *
 * 明示的なopt-in操作専用であり、bow-tie修復や通常の診断から自動では呼ばない。
 * standalone polygonは対象外とする。削除faceだけから参照されていた頂点はcompactするが、
 * 入力時点から孤立していた頂点は対象外として保持する。
 */
[[nodiscard]] SingleTriangleShellRemovalResult plan_single_triangle_shell_removal(
    const RawTopologyView& topology);

}  // namespace ywta::mesh_core
