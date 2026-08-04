#include "autoRemesherNode.h"

#include <maya/MComputation.h>
#include <maya/MFnEnumAttribute.h>
#include <maya/MFnMesh.h>
#include <maya/MFnMeshData.h>
#include <maya/MFnNumericAttribute.h>
#include <maya/MFnTypedAttribute.h>
#include <maya/MGlobal.h>
#include <maya/MPoint.h>

// AutoRemesher コア（cpp/autoremesher_core/CMakeLists.txt が静的リンクする
// autoremesher_core）を直接呼び出す。qtshim (cpp/autoremesher_core/qtshim) が
// Qt非依存ビルドとgeogram/version.hの不具合回避を提供しているので、
// 通常のインクルードパスとして machinery 側 (CMakeLists) が qtshim を
// autoremesher_core の PUBLIC include path として渡してくれる。
#include <AutoRemesher/AutoRemesher>
#include <AutoRemesher/Vector3>
#include <geogram/basic/common.h>

#include <cstring>
#include <mutex>

namespace {

// geogram はプロセス中で一度だけ初期化する必要がある。
// (cpp/autoremesher_core/capi.cpp の ensureGeogramInitialized() と同じ対策)
void EnsureGeogramInitialized() {
  static std::once_flag initialized;
  std::call_once(initialized, []() { GEO::initialize(GEO::GEOGRAM_INSTALL_HANDLERS); });
}

uint64_t HashCombine(uint64_t seed, uint64_t value) {
  // boost::hash_combine 相当（64bit版）
  return seed ^ (value + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2));
}

uint64_t HashDouble(double v) {
  uint64_t bits;
  std::memcpy(&bits, &v, sizeof(bits));
  return bits;
}

}  // namespace

MTypeId AutoRemesherNode::id(0x0011581C);
const MString AutoRemesherNode::kName("autoRemesherNode");

MObject AutoRemesherNode::aInMesh;
MObject AutoRemesherNode::aOutMesh;
MObject AutoRemesherNode::aEnable;
MObject AutoRemesherNode::aTargetCount;
MObject AutoRemesherNode::aAdaptivity;
MObject AutoRemesherNode::aEdgeScaling;
MObject AutoRemesherNode::aModelType;

AutoRemesherNode::AutoRemesherNode() : cacheValid_(false), cachedInputHash_(0) {}

AutoRemesherNode::~AutoRemesherNode() {}

void* AutoRemesherNode::creator() { return new AutoRemesherNode(); }

MStatus AutoRemesherNode::initialize() {
  MStatus status;

  MFnTypedAttribute tAttr;
  MFnNumericAttribute nAttr;
  MFnEnumAttribute eAttr;

  aInMesh = tAttr.create("inMesh", "inMesh", MFnData::kMesh, MObject::kNullObj, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  tAttr.setStorable(false);
  addAttribute(aInMesh);

  aOutMesh = tAttr.create("outMesh", "outMesh", MFnData::kMesh, MObject::kNullObj, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  tAttr.setWritable(false);
  tAttr.setStorable(false);
  addAttribute(aOutMesh);

  aEnable = nAttr.create("enable", "enable", MFnNumericData::kBoolean, 0.0, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  nAttr.setKeyable(true);
  addAttribute(aEnable);

  aTargetCount = nAttr.create("targetCount", "targetCount", MFnNumericData::kInt, 8000, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  nAttr.setKeyable(true);
  nAttr.setMin(100);
  addAttribute(aTargetCount);

  aAdaptivity = nAttr.create("adaptivity", "adaptivity", MFnNumericData::kDouble, 1.0, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  nAttr.setKeyable(true);
  nAttr.setMin(0.0);
  nAttr.setMax(1.0);
  addAttribute(aAdaptivity);

  aEdgeScaling = nAttr.create("edgeScaling", "edgeScaling", MFnNumericData::kDouble, 1.0, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  nAttr.setKeyable(true);
  nAttr.setMin(0.0);
  addAttribute(aEdgeScaling);

  aModelType = eAttr.create("modelType", "modelType", 0, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  eAttr.setKeyable(true);
  eAttr.addField("Organic", AutoRemesherNode::kOrganic);
  eAttr.addField("HardSurface", AutoRemesherNode::kHardSurface);
  addAttribute(aModelType);

  attributeAffects(aInMesh, aOutMesh);
  attributeAffects(aEnable, aOutMesh);
  attributeAffects(aTargetCount, aOutMesh);
  attributeAffects(aAdaptivity, aOutMesh);
  attributeAffects(aEdgeScaling, aOutMesh);
  attributeAffects(aModelType, aOutMesh);

  return MS::kSuccess;
}

MStatus AutoRemesherNode::compute(const MPlug& plug, MDataBlock& data) {
  MStatus status;

  if (plug != aOutMesh) {
    return MS::kUnknownParameter;
  }

  MDataHandle hInMesh = data.inputValue(aInMesh, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);
  MObject inMesh = hInMesh.asMesh();

  MDataHandle hOutput = data.outputValue(aOutMesh, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  bool enable = data.inputValue(aEnable).asBool();

  if (!enable || inMesh.isNull()) {
    status = passthrough(inMesh, hOutput);
    CHECK_MSTATUS_AND_RETURN_IT(status);
    data.setClean(plug);
    return MS::kSuccess;
  }

  int targetCount = data.inputValue(aTargetCount).asInt();
  double adaptivity = data.inputValue(aAdaptivity).asDouble();
  double edgeScaling = data.inputValue(aEdgeScaling).asDouble();
  short modelType = data.inputValue(aModelType).asShort();

  status = remesh(inMesh, targetCount, adaptivity, edgeScaling, modelType, hOutput);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  data.setClean(plug);
  return MS::kSuccess;
}

MStatus AutoRemesherNode::passthrough(const MObject& inMesh, MDataHandle& hOutput) {
  MStatus status;
  MFnMeshData outputDataCreator;
  MObject newOutputData = outputDataCreator.create(&status);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  if (!inMesh.isNull()) {
    MFnMesh outMeshFn;
    outMeshFn.copy(inMesh, newOutputData, &status);
    CHECK_MSTATUS_AND_RETURN_IT(status);
  }

  hOutput.set(newOutputData);
  hOutput.setClean();
  return MS::kSuccess;
}

MStatus AutoRemesherNode::remesh(const MObject& inMesh, int targetCount, double adaptivity,
                                 double edgeScaling, short modelType, MDataHandle& hOutput) {
  MStatus status;

  MFnMesh inMeshFn(inMesh, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  MPointArray points;
  status = inMeshFn.getPoints(points, MSpace::kObject);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  MIntArray triangleCounts;
  MIntArray triangleVertices;
  status = inMeshFn.getTriangles(triangleCounts, triangleVertices);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  if (points.length() == 0 || triangleVertices.length() < 3) {
    // 三角形化できない/空のメッシュはそのままパススルーする
    return passthrough(inMesh, hOutput);
  }

  uint64_t inputHash = computeInputHash(points, triangleCounts, triangleVertices, targetCount,
                                        adaptivity, edgeScaling, modelType);

  if (!(cacheValid_ && inputHash == cachedInputHash_)) {
    EnsureGeogramInitialized();

    std::vector<AutoRemesher::Vector3> inputVertices;
    inputVertices.reserve(points.length());
    for (unsigned int i = 0; i < points.length(); ++i) {
      inputVertices.push_back(
          AutoRemesher::Vector3(points[i].x, points[i].y, points[i].z));
    }

    std::vector<std::vector<size_t>> inputTriangles;
    unsigned int triangleCount = triangleVertices.length() / 3;
    inputTriangles.reserve(triangleCount);
    for (unsigned int i = 0; i < triangleCount; ++i) {
      std::vector<size_t> triangle;
      triangle.reserve(3);
      triangle.push_back((size_t)triangleVertices[i * 3 + 0]);
      triangle.push_back((size_t)triangleVertices[i * 3 + 1]);
      triangle.push_back((size_t)triangleVertices[i * 3 + 2]);
      inputTriangles.push_back(std::move(triangle));
    }

    AutoRemesher::AutoRemesher autoRemesher(inputVertices, inputTriangles);
    if (targetCount > 0) {
      autoRemesher.setTargetTriangleCount((size_t)targetCount);
    }
    // AutoRemesher::m_scaling の既定値は 0.0 だが、そのまま
    // GEO::GlobalParam2d::quad_cover() に渡すと結果が退化する
    // （本家GUIの既定値は 1.0。cpp/autoremesher_core/capi.cpp の同種の
    // 補正を踏襲する）。
    autoRemesher.setScaling(edgeScaling > 0.0 ? edgeScaling : 1.0);
    if (adaptivity > 0.0) {
      autoRemesher.setGradientAdaptivity(adaptivity);
    }
    autoRemesher.setModelType(AutoRemesherNode::kHardSurface == modelType
                                  ? AutoRemesher::ModelType::HardSurface
                                  : AutoRemesher::ModelType::Organic);
    autoRemesher.setProgressHandler(&AutoRemesherNode::progressHandler);
    autoRemesher.setTag(this);

    // MComputationはコア側に本当の中断APIが無いため、進捗/ビジー表示のみに使う。
    MComputation computation;
    computation.beginComputation();

    bool ok = autoRemesher.remesh();

    computation.endComputation();

    if (!ok) {
      MGlobal::displayWarning(
          "AutoRemesherNode: remesh() failed. Falling back to the original mesh.");
      return passthrough(inMesh, hOutput);
    }

    const std::vector<AutoRemesher::Vector3>& remeshedVertices = autoRemesher.remeshedVertices();
    const std::vector<std::vector<size_t>>& remeshedFaces = autoRemesher.remeshedQuads();

    if (remeshedVertices.empty() || remeshedFaces.empty()) {
      MGlobal::displayWarning(
          "AutoRemesherNode: remesh() returned an empty result. Falling back to the original "
          "mesh.");
      return passthrough(inMesh, hOutput);
    }

    cachedOutPoints_.clear();
    cachedOutPoints_.setLength((unsigned int)remeshedVertices.size());
    for (size_t i = 0; i < remeshedVertices.size(); ++i) {
      const AutoRemesher::Vector3& v = remeshedVertices[i];
      cachedOutPoints_.set((unsigned int)i, v.x(), v.y(), v.z());
    }

    cachedOutPolygonCounts_.clear();
    cachedOutPolygonCounts_.setLength((unsigned int)remeshedFaces.size());
    cachedOutPolygonConnects_.clear();
    unsigned int connectIndex = 0;
    // 事前に接続配列の総数を数えて確保する
    unsigned int totalConnects = 0;
    for (size_t i = 0; i < remeshedFaces.size(); ++i) {
      totalConnects += (unsigned int)remeshedFaces[i].size();
    }
    cachedOutPolygonConnects_.setLength(totalConnects);
    for (size_t i = 0; i < remeshedFaces.size(); ++i) {
      const std::vector<size_t>& face = remeshedFaces[i];
      cachedOutPolygonCounts_.set((int)face.size(), (unsigned int)i);
      for (size_t vertexIndex : face) {
        cachedOutPolygonConnects_.set((int)vertexIndex, connectIndex++);
      }
    }

    cachedInputHash_ = inputHash;
    cacheValid_ = true;
  }

  MFnMeshData outputDataCreator;
  MObject newOutputData = outputDataCreator.create(&status);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  MFnMesh outMeshFn;
  outMeshFn.create((int)cachedOutPoints_.length(), (int)cachedOutPolygonCounts_.length(),
                   cachedOutPoints_, cachedOutPolygonCounts_, cachedOutPolygonConnects_,
                   newOutputData, &status);
  CHECK_MSTATUS_AND_RETURN_IT(status);

  hOutput.set(newOutputData);
  hOutput.setClean();
  return MS::kSuccess;
}

uint64_t AutoRemesherNode::computeInputHash(const MPointArray& points,
                                            const MIntArray& triangleCounts,
                                            const MIntArray& triangleVertices, int targetCount,
                                            double adaptivity, double edgeScaling,
                                            short modelType) {
  uint64_t hash = 1469598103934665603ULL;  // FNV offset basis
  hash = HashCombine(hash, (uint64_t)points.length());
  for (unsigned int i = 0; i < points.length(); ++i) {
    hash = HashCombine(hash, HashDouble(points[i].x));
    hash = HashCombine(hash, HashDouble(points[i].y));
    hash = HashCombine(hash, HashDouble(points[i].z));
  }
  hash = HashCombine(hash, (uint64_t)triangleCounts.length());
  hash = HashCombine(hash, (uint64_t)triangleVertices.length());
  for (unsigned int i = 0; i < triangleVertices.length(); ++i) {
    hash = HashCombine(hash, (uint64_t)triangleVertices[i]);
  }
  hash = HashCombine(hash, (uint64_t)targetCount);
  hash = HashCombine(hash, HashDouble(adaptivity));
  hash = HashCombine(hash, HashDouble(edgeScaling));
  hash = HashCombine(hash, (uint64_t)modelType);
  return hash;
}

void AutoRemesherNode::progressHandler(void* /*tag*/, float /*progress*/, const char* /*status*/) {
  // AutoRemesher内部の呼び出しスレッドが不定なため、Maya APIは呼ばない。
  // (将来的にメインスレッドからポーリングする方式に変更する余地を残す)
}
