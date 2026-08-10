#include "ywta/mesh_core/raw_topology.h"

#include <algorithm>
#include <limits>
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

SingleTriangleShellRemovalResult removal_error_result(TopologyStatus status, std::string message) {
  SingleTriangleShellRemovalResult result;
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

struct EdgeUse {
  std::uint32_t first = 0;
  std::uint32_t second = 0;
  std::uint64_t face = 0;
};

bool edge_less(const EdgeUse& left, const EdgeUse& right) {
  if (left.first != right.first) {
    return left.first < right.first;
  }
  if (left.second != right.second) {
    return left.second < right.second;
  }
  return left.face < right.face;
}

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

SingleTriangleShellRemovalResult plan_single_triangle_shell_removal(
    const RawTopologyView& topology) {
  const BowTieSplitResult validation = validate(topology);
  if (!validation.ok()) {
    return removal_error_result(validation.status, validation.message);
  }

  std::vector<EdgeUse> edges;
  edges.reserve(static_cast<std::size_t>(topology.face_vertex_count));
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    for (std::uint64_t corner = begin; corner < end; ++corner) {
      const std::uint64_t next = corner + 1 == end ? begin : corner + 1;
      const std::uint32_t left = topology.face_vertices[corner];
      const std::uint32_t right = topology.face_vertices[next];
      edges.push_back({std::min(left, right), std::max(left, right), face});
    }
  }
  std::sort(edges.begin(), edges.end(), edge_less);

  std::vector<std::uint8_t> face_has_edge_neighbor(static_cast<std::size_t>(topology.face_count),
                                                   0);
  std::size_t group_begin = 0;
  while (group_begin < edges.size()) {
    std::size_t group_end = group_begin + 1;
    while (group_end < edges.size() && edges[group_end].first == edges[group_begin].first &&
           edges[group_end].second == edges[group_begin].second) {
      ++group_end;
    }
    if (group_end - group_begin > 1) {
      for (std::size_t edge = group_begin; edge < group_end; ++edge) {
        face_has_edge_neighbor[edges[edge].face] = 1;
      }
    }
    group_begin = group_end;
  }

  SingleTriangleShellRemovalResult result;
  SingleTriangleShellRemovalPlan& plan = result.plan;
  plan.original_vertex_count = topology.vertex_count;
  plan.original_face_count = topology.face_count;
  plan.retained_face_offsets.reserve(static_cast<std::size_t>(topology.face_count) + 1);
  plan.retained_face_vertices.reserve(static_cast<std::size_t>(topology.face_vertex_count));
  plan.source_face_by_output.reserve(static_cast<std::size_t>(topology.face_count));
  plan.output_face_by_source.assign(static_cast<std::size_t>(topology.face_count), kRemovedElement);
  plan.source_corner_by_output.reserve(static_cast<std::size_t>(topology.face_vertex_count));
  plan.retained_face_offsets.push_back(0);

  std::vector<std::uint8_t> source_vertex_was_used(topology.vertex_count, 0);
  for (std::uint64_t corner = 0; corner < topology.face_vertex_count; ++corner) {
    source_vertex_was_used[topology.face_vertices[corner]] = 1;
  }

  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    const bool is_single_triangle = end - begin == 3 && face_has_edge_neighbor[face] == 0;
    if (is_single_triangle) {
      plan.removed_source_faces.push_back(face);
      continue;
    }

    plan.output_face_by_source[face] = plan.source_face_by_output.size();
    plan.source_face_by_output.push_back(face);
    for (std::uint64_t corner = begin; corner < end; ++corner) {
      plan.retained_face_vertices.push_back(topology.face_vertices[corner]);
      plan.source_corner_by_output.push_back(corner);
    }
    plan.retained_face_offsets.push_back(plan.retained_face_vertices.size());
  }
  plan.output_face_count = plan.source_face_by_output.size();

  std::vector<std::uint8_t> retained_vertex_is_used(topology.vertex_count, 0);
  for (const std::uint32_t vertex : plan.retained_face_vertices) {
    retained_vertex_is_used[vertex] = 1;
  }
  plan.output_vertex_by_source.assign(topology.vertex_count, kRemovedElement);
  plan.source_vertex_by_output.reserve(topology.vertex_count);
  for (std::uint32_t vertex = 0; vertex < topology.vertex_count; ++vertex) {
    const bool became_isolated =
        source_vertex_was_used[vertex] != 0 && retained_vertex_is_used[vertex] == 0;
    if (became_isolated) {
      continue;
    }
    plan.output_vertex_by_source[vertex] = plan.source_vertex_by_output.size();
    plan.source_vertex_by_output.push_back(vertex);
  }
  for (std::uint32_t& vertex : plan.retained_face_vertices) {
    vertex = static_cast<std::uint32_t>(plan.output_vertex_by_source[vertex]);
  }
  plan.output_vertex_count = plan.source_vertex_by_output.size();
  return result;
}

}  // namespace ywta::mesh_core
