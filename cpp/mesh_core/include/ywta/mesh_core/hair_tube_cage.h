#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "ywta/mesh_core/hair_tube_topology.h"

namespace ywta::mesh_core {

/** DCCに依存しない倍精度3次元点。 */
struct Point3d {
  double x = 0.0;
  double y = 0.0;
  double z = 0.0;
};

/** DCCの位置配列を所有せず参照するview。 */
struct Point3dView {
  const Point3d* points = nullptr;
  std::uint64_t count = 0;
};

/** Curve Cageの構築または再生成状態。 */
enum class HairTubeCageStatus {
  kOk = 0,
  kInvalidTopologyLayout,
  kNullPositions,
  kPositionIndexOutOfRange,
  kNonFinitePosition,
  kInvalidFitTolerance,
  kZeroLengthStationInterval,
  kParameterOutOfRange,
  kTargetSegmentsZero,
  kOutputOverflow,
  kNonFiniteEvaluation,
  kZeroAreaQuad,
  kInvertedQuad,
  kSelfIntersection,
};

/** 1区間の自然三次スプライン係数。P(x)=a+b*x+c*x^2+d*x^3。 */
struct CubicSegment3d {
  double t0 = 0.0;
  double t1 = 0.0;
  Point3d a;
  Point3d b;
  Point3d c;
  Point3d d;
};

/** 4 rail、共有t、source polyline、cubic fitを保持するCurve Cage。 */
struct HairTubeCurveCage {
  std::uint64_t source_station_count = 0;
  std::vector<double> shared_t;
  std::vector<Point3d> source_points;
  std::vector<CubicSegment3d> cubic_segments;
  double fit_tolerance = 0.0;
  double max_fit_deviation = 0.0;
  bool cubic_active = false;
};

/** Curve Cage構築結果。 */
struct HairTubeCageResult {
  HairTubeCageStatus status = HairTubeCageStatus::kOk;
  std::string message;
  HairTubeCurveCage cage;

  [[nodiscard]] bool ok() const noexcept { return status == HairTubeCageStatus::kOk; }
};

/** 評価点が属するsource station区間。 */
struct HairTubeSourceSample {
  std::uint64_t interval = 0;
  double alpha = 0.0;
};

/** 共有tで評価した4 railの断面。 */
struct HairTubeCageSample {
  std::array<Point3d, 4> points;
  HairTubeSourceSample source;
};

/** Curve Cage評価結果。 */
struct HairTubeCageSampleResult {
  HairTubeCageStatus status = HairTubeCageStatus::kOk;
  std::string message;
  HairTubeCageSample sample;

  [[nodiscard]] bool ok() const noexcept { return status == HairTubeCageStatus::kOk; }
};

/** 固定密度で再生成したopen quad tube。 */
struct HairTubeGeneratedMesh {
  std::vector<Point3d> positions;
  std::vector<std::uint32_t> quad_indices;
  std::vector<HairTubeSourceSample> source_mapping;
  double max_source_distance = 0.0;
};

/** 固定密度再生成結果。 */
struct HairTubeGeneratedMeshResult {
  HairTubeCageStatus status = HairTubeCageStatus::kOk;
  std::string message;
  HairTubeGeneratedMesh mesh;

  [[nodiscard]] bool ok() const noexcept { return status == HairTubeCageStatus::kOk; }
};

/**
 * HairTubeTopologyとsource位置から共有t付きCurve Cageを構築する。
 *
 * fit_toleranceが0ならpolyline Oracleを使用する。自然三次スプラインとOracleの
 * 計測偏差が許容値を超える場合も、入力を変更せずpolylineへfallbackする。
 */
[[nodiscard]] HairTubeCageResult build_hair_tube_curve_cage(const HairTubeTopology& topology,
                                                            const Point3dView& positions,
                                                            double fit_tolerance);

/** 共有tの0〜1でCurve Cageを評価する。 */
[[nodiscard]] HairTubeCageSampleResult evaluate_hair_tube_curve_cage(const HairTubeCurveCage& cage,
                                                                     double t);

/** Curve Cageから指定segment数のopen quad tubeを別bufferへ再生成する。 */
[[nodiscard]] HairTubeGeneratedMeshResult regenerate_hair_tube_fixed_density(
    const HairTubeCurveCage& cage, std::uint64_t target_segments);

}  // namespace ywta::mesh_core
