#ifndef AUTOREMESHER_AUTOREMESHERNODE_H
#define AUTOREMESHER_AUTOREMESHERNODE_H

#include <maya/MIntArray.h>
#include <maya/MPointArray.h>
#include <maya/MPxNode.h>

#include <cstdint>

// AutoRemesherNode
//
// inMesh を非破壊にクアッドリメッシュする MPxNode。
// enable=false のときは inMesh をそのまま outMesh へパススルーする。
// enable=true のときは autoremesher_core (external/autoremesher の
// Qt非依存コア) を静的リンクして呼び出し、結果のクアッドメッシュを
// outMesh として構築する。
//
// 同一の入力トポロジ/頂点位置/パラメータであれば再計算せず、キャッシュした
// 結果を再利用する（DGノードの再評価コストを抑えるため）。
class AutoRemesherNode : public MPxNode {
 public:
  AutoRemesherNode();
  virtual ~AutoRemesherNode();
  static void* creator();

  virtual MStatus compute(const MPlug& plug, MDataBlock& data) override;

  static MStatus initialize();

  static MTypeId id;
  static const MString kName;

  static MObject aInMesh;
  static MObject aOutMesh;
  static MObject aEnable;
  static MObject aTargetCount;
  static MObject aAdaptivity;
  static MObject aEdgeScaling;
  static MObject aModelType;

  enum ModelType { kOrganic = 0, kHardSurface = 1 };

 private:
  // inMesh をそのまま outMesh にコピーする。
  MStatus passthrough(const MObject& inMesh, MDataHandle& hOutput);

  // autoremesher_core を呼び出してクアッドリメッシュを実行し、outMesh を構築する。
  // 失敗した場合は inMesh をそのままコピーする（passthrough にフォールバック）。
  MStatus remesh(const MObject& inMesh, int targetCount, double adaptivity, double edgeScaling,
                 short modelType, MDataHandle& hOutput);

  // 入力トポロジ/頂点位置とパラメータからキャッシュキーとなるハッシュ値を計算する。
  static uint64_t computeInputHash(const MPointArray& points, const MIntArray& triangleCounts,
                                   const MIntArray& triangleVertices, int targetCount,
                                   double adaptivity, double edgeScaling, short modelType);

  // AutoRemesher::AutoRemesherProgressHandler 互換のコールバック。
  // AutoRemesher内部はTBBで並列化されている場合があり、呼び出しスレッドが
  // メインスレッドとは限らないため、Maya APIは一切呼ばずに無視する
  // （MComputationによる本当の中断はコア側にAPIが無いためサポートしない）。
  static void progressHandler(void* tag, float progress, const char* status);

  bool cacheValid_;
  uint64_t cachedInputHash_;
  MPointArray cachedOutPoints_;
  MIntArray cachedOutPolygonCounts_;
  MIntArray cachedOutPolygonConnects_;
};

#endif
