#include "ywta/mesh_core/raw_topology.h"

#include <algorithm>
#include <limits>
#include <map>
#include <numeric>
#include <sstream>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace ywta::mesh_core {
namespace {

BowTieSplitResult error_result(TopologyStatus status, std::string message) {
  BowTieSplitResult result;
  result.status = status;
  result.message = std::move(message);
  return result;
}

BowTieSplitResult validate(const RawTopologyView& topology) {
  if (topology.face_offsets == nullptr) {
    return error_result(TopologyStatus::kNullFaceOffsets, "face_offsets is null");
  }
  if (topology.face_vertex_count > 0 && topology.face_vertices == nullptr) {
    return error_result(TopologyStatus::kNullFaceVertices, "face_vertices is null");
  }
  if (topology.face_offsets[0] != 0 ||
      topology.face_offsets[topology.face_count] != topology.face_vertex_count) {
    return error_result(TopologyStatus::kInvalidFaceOffsets,
                        "face_offsets must start at zero and end at face_vertex_count");
  }

  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    if (end < begin || end > topology.face_vertex_count) {
      std::ostringstream message;
      message << "face_offsets is not monotonic at face " << face;
      return error_result(TopologyStatus::kInvalidFaceOffsets, message.str());
    }
    if (end - begin < 3) {
      std::ostringstream message;
      message << "face " << face << " has fewer than three vertices";
      return error_result(TopologyStatus::kFaceTooSmall, message.str());
    }

    std::unordered_set<std::uint32_t> vertices;
    vertices.reserve(static_cast<std::size_t>(end - begin));
    for (std::uint64_t corner = begin; corner < end; ++corner) {
      const std::uint32_t vertex = topology.face_vertices[corner];
      if (vertex >= topology.vertex_count) {
        std::ostringstream message;
        message << "vertex index " << vertex << " is out of range at corner " << corner;
        return error_result(TopologyStatus::kVertexIndexOutOfRange, message.str());
      }
      if (!vertices.insert(vertex).second) {
        std::ostringstream message;
        message << "face " << face << " contains vertex " << vertex << " more than once";
        return error_result(TopologyStatus::kRepeatedFaceVertex, message.str());
      }
    }
  }
  return {};
}

class DisjointSet {
 public:
  explicit DisjointSet(std::size_t size) : parent_(size), rank_(size, 0) {
    std::iota(parent_.begin(), parent_.end(), 0);
  }

  std::size_t find(std::size_t value) {
    while (parent_[value] != value) {
      parent_[value] = parent_[parent_[value]];
      value = parent_[value];
    }
    return value;
  }

  void unite(std::size_t left, std::size_t right) {
    left = find(left);
    right = find(right);
    if (left == right) {
      return;
    }
    if (rank_[left] < rank_[right]) {
      std::swap(left, right);
    }
    parent_[right] = left;
    if (rank_[left] == rank_[right]) {
      ++rank_[left];
    }
  }

 private:
  std::vector<std::size_t> parent_;
  std::vector<std::uint8_t> rank_;
};

}  // namespace

BowTieSplitResult plan_bow_tie_vertex_splits(const RawTopologyView& topology) {
  BowTieSplitResult validation = validate(topology);
  if (!validation.ok()) {
    return validation;
  }

  BowTieSplitResult result;
  BowTieSplitPlan& plan = result.plan;
  plan.original_vertex_count = topology.vertex_count;
  plan.output_vertex_count = topology.vertex_count;
  if (topology.face_vertex_count > 0) {
    plan.rewritten_face_vertices.assign(topology.face_vertices,
                                        topology.face_vertices + topology.face_vertex_count);
  }
  plan.source_vertex_by_output.resize(topology.vertex_count);
  std::iota(plan.source_vertex_by_output.begin(), plan.source_vertex_by_output.end(), 0);
  plan.source_to_output_offsets.reserve(static_cast<std::size_t>(topology.vertex_count) + 1);
  plan.source_to_output_vertices.reserve(topology.vertex_count);
  plan.source_to_output_offsets.push_back(0);

  std::vector<std::uint64_t> incident_offsets(static_cast<std::size_t>(topology.vertex_count) + 1,
                                              0);
  for (std::uint64_t corner = 0; corner < topology.face_vertex_count; ++corner) {
    ++incident_offsets[static_cast<std::size_t>(topology.face_vertices[corner]) + 1];
  }
  std::partial_sum(incident_offsets.begin(), incident_offsets.end(), incident_offsets.begin());

  std::vector<std::uint64_t> incident_corners(topology.face_vertex_count);
  std::vector<std::uint64_t> incident_faces(topology.face_vertex_count);
  std::vector<std::uint64_t> write_offsets = incident_offsets;
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    for (std::uint64_t corner = topology.face_offsets[face];
         corner < topology.face_offsets[face + 1]; ++corner) {
      const std::uint32_t vertex = topology.face_vertices[corner];
      const std::uint64_t destination = write_offsets[vertex]++;
      incident_corners[destination] = corner;
      incident_faces[destination] = face;
    }
  }

  std::uint64_t next_vertex = topology.vertex_count;
  for (std::uint32_t vertex = 0; vertex < topology.vertex_count; ++vertex) {
    const std::uint64_t incident_begin = incident_offsets[vertex];
    const std::uint64_t incident_end = incident_offsets[static_cast<std::size_t>(vertex) + 1];
    const std::size_t incident_count = static_cast<std::size_t>(incident_end - incident_begin);

    plan.source_to_output_vertices.push_back(vertex);
    if (incident_count > 1) {
      DisjointSet fans(incident_count);
      std::unordered_map<std::uint32_t, std::size_t> first_corner_by_neighbor;
      first_corner_by_neighbor.reserve(incident_count * 2);

      for (std::size_t local = 0; local < incident_count; ++local) {
        const std::uint64_t item = incident_begin + local;
        const std::uint64_t corner = incident_corners[item];
        const std::uint64_t face = incident_faces[item];
        const std::uint64_t face_begin = topology.face_offsets[face];
        const std::uint64_t face_end = topology.face_offsets[face + 1];
        const std::uint64_t previous = corner == face_begin ? face_end - 1 : corner - 1;
        const std::uint64_t next = corner + 1 == face_end ? face_begin : corner + 1;

        for (const std::uint64_t adjacent_corner : {previous, next}) {
          const std::uint32_t neighbor = topology.face_vertices[adjacent_corner];
          const auto [found, inserted] = first_corner_by_neighbor.emplace(neighbor, local);
          if (!inserted) {
            fans.unite(local, found->second);
          }
        }
      }

      std::unordered_map<std::size_t, std::uint32_t> output_by_root;
      output_by_root.reserve(incident_count);
      output_by_root.emplace(fans.find(0), vertex);

      for (std::size_t local = 0; local < incident_count; ++local) {
        const std::size_t root = fans.find(local);
        auto output = output_by_root.find(root);
        if (output == output_by_root.end()) {
          if (next_vertex > std::numeric_limits<std::uint32_t>::max()) {
            return error_result(TopologyStatus::kOutputVertexOverflow,
                                "bow-tie split exceeds the uint32 vertex index range");
          }
          const std::uint32_t new_vertex = static_cast<std::uint32_t>(next_vertex++);
          output = output_by_root.emplace(root, new_vertex).first;
          plan.source_vertex_by_output.push_back(vertex);
          plan.source_to_output_vertices.push_back(new_vertex);
        }
        plan.rewritten_face_vertices[incident_corners[incident_begin + local]] = output->second;
      }

      if (output_by_root.size() > 1) {
        BowTieVertexSplit split;
        split.source_vertex = vertex;
        const std::uint64_t mapping_begin = plan.source_to_output_offsets.back();
        split.output_vertices.assign(
            plan.source_to_output_vertices.begin() + static_cast<std::ptrdiff_t>(mapping_begin),
            plan.source_to_output_vertices.end());
        plan.splits.push_back(std::move(split));
      }
    }
    plan.source_to_output_offsets.push_back(plan.source_to_output_vertices.size());
  }

  plan.output_vertex_count = next_vertex;
  return result;
}

ManifoldSplitResult plan_manifold_splits(const RawTopologyView& topology) {
  const BowTieSplitResult validation = validate(topology);
  if (!validation.ok()) {
    ManifoldSplitResult result;
    result.status = validation.status;
    result.message = validation.message;
    return result;
  }

  ManifoldSplitResult result;
  ManifoldSplitPlan& plan = result.plan;
  plan.original_vertex_count = topology.vertex_count;
  plan.output_vertex_count = topology.vertex_count;
  if (topology.face_vertex_count > 0) {
    plan.rewritten_face_vertices.assign(topology.face_vertices,
                                        topology.face_vertices + topology.face_vertex_count);
  }
  plan.source_vertex_by_output.resize(topology.vertex_count);
  std::iota(plan.source_vertex_by_output.begin(), plan.source_vertex_by_output.end(), 0);

  struct EdgeUse {
    std::uint64_t face;
    std::uint64_t first_corner;
    std::uint64_t second_corner;
  };
  std::map<std::pair<std::uint32_t, std::uint32_t>, std::vector<EdgeUse>> uses_by_edge;
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    for (std::uint64_t corner = begin; corner < end; ++corner) {
      const std::uint64_t next = corner + 1 == end ? begin : corner + 1;
      const std::uint32_t first = topology.face_vertices[corner];
      const std::uint32_t second = topology.face_vertices[next];
      uses_by_edge[{std::min(first, second), std::max(first, second)}].push_back(
          {face, corner, next});
    }
  }

  std::map<std::pair<std::uint64_t, std::uint32_t>, std::uint32_t> duplicate_by_face_vertex;
  std::uint64_t next_vertex = topology.vertex_count;
  for (const auto& [edge, uses] : uses_by_edge) {
    if (uses.size() <= 2) {
      continue;
    }
    plan.split_non_manifold_edges.insert(plan.split_non_manifold_edges.end(),
                                         {edge.first, edge.second});
    for (std::size_t use_index = 2; use_index < uses.size(); ++use_index) {
      const EdgeUse& use = uses[use_index];
      for (const std::uint64_t corner : {use.first_corner, use.second_corner}) {
        const std::uint32_t source = topology.face_vertices[corner];
        const auto key = std::make_pair(use.face, source);
        auto duplicate = duplicate_by_face_vertex.find(key);
        if (duplicate == duplicate_by_face_vertex.end()) {
          if (next_vertex > std::numeric_limits<std::uint32_t>::max()) {
            result.status = TopologyStatus::kOutputVertexOverflow;
            result.message = "manifold split exceeds the uint32 vertex index range";
            result.plan = {};
            return result;
          }
          const std::uint32_t output = static_cast<std::uint32_t>(next_vertex++);
          duplicate = duplicate_by_face_vertex.emplace(key, output).first;
          plan.source_vertex_by_output.push_back(source);
        }
        plan.rewritten_face_vertices[corner] = duplicate->second;
      }
    }
  }

  const std::vector<std::uint64_t> offsets(topology.face_offsets,
                                           topology.face_offsets + topology.face_count + 1);
  const BowTieSplitResult fan_result = plan_bow_tie_vertex_splits(
      {static_cast<std::uint32_t>(next_vertex), offsets.data(), topology.face_count,
       plan.rewritten_face_vertices.data(), topology.face_vertex_count});
  if (!fan_result.ok()) {
    result.status = fan_result.status;
    result.message = fan_result.message;
    result.plan = {};
    return result;
  }

  std::vector<std::uint32_t> composed_sources;
  composed_sources.reserve(fan_result.plan.source_vertex_by_output.size());
  for (const std::uint32_t intermediate : fan_result.plan.source_vertex_by_output) {
    composed_sources.push_back(plan.source_vertex_by_output[intermediate]);
  }
  plan.rewritten_face_vertices = fan_result.plan.rewritten_face_vertices;
  plan.source_vertex_by_output = std::move(composed_sources);
  plan.output_vertex_count = fan_result.plan.output_vertex_count;
  for (const BowTieVertexSplit& split : fan_result.plan.splits) {
    plan.split_source_vertices.push_back(plan.source_vertex_by_output[split.output_vertices[0]]);
  }
  return result;
}

}  // namespace ywta::mesh_core
