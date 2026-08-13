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

/** 非多様体edgeと複数vertex fanを頂点複製だけで分離する計画。 */
struct ManifoldSplitPlan {
  std::uint32_t original_vertex_count = 0;
  std::uint64_t output_vertex_count = 0;
  std::vector<std::uint32_t> rewritten_face_vertices;
  std::vector<std::uint32_t> source_vertex_by_output;
  std::vector<std::uint32_t> split_non_manifold_edges;
  std::vector<std::uint32_t> split_source_vertices;
};

/** split-to-manifold計画の作成結果。 */
struct ManifoldSplitResult {
  TopologyStatus status = TopologyStatus::kOk;
  std::string message;
  ManifoldSplitPlan plan;

  [[nodiscard]] bool ok() const noexcept { return status == TopologyStatus::kOk; }
};

/**
 * 頂点周りのface fanを共有edgeで連結し、複数fanを持つ頂点の分離計画を作る。
 *
 * 頂点位置やface数は変更しない。構造的に不正な入力は部分結果を返さず拒否する。
 */
[[nodiscard]] BowTieSplitResult plan_bow_tie_vertex_splits(const RawTopologyView& topology);

/**
 * 3面以上で共有されるedge useと、分離したvertex fanを頂点複製で分離する。
 *
 * face/corner順は変更しないため、corner属性は同じindexからコピーできる。
 * source_vertex_by_outputを使うとpoint属性を元頂点から複製できる。
 */
[[nodiscard]] ManifoldSplitResult plan_manifold_splits(const RawTopologyView& topology);

}  // namespace ywta::mesh_core
