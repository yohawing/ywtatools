# Mesh ツール

[← ツールガイドへ戻る](README.md)

メニュー: `YWTA > Mesh`

## 頂点をロックする

`Lock Selected Vertices` / `Unlock Selected Vertices`

Polygon Vertexを選択して実行します。Geometryは変わりませんが、頂点のLock属性は変更されます。
一括Undoや失敗時の復元を持たない従来処理なので、少数の頂点でMaya Undoを確認してから
使ってください。頂点を選ばずに実行するとエラーになる場合があります。

## 階層をJointとSkinned Meshへ変換する

### Merge Objects and Skinning

選択したTransform階層をJoint化し、子孫Meshを結合してBindします。

1. 変換したい階層のRoot Transformを選択します。
2. `YWTA > Mesh > Merge Objects and Skinning` を実行します。
3. 生成されたJoint、結合Mesh、SkinClusterを確認します。

最初に選択したTransformだけを使う従来処理です。名前の衝突や途中失敗に対する一括復元が
ないため、**要バックアップ**です。

## クアッドへリメッシュする

### AutoRemesher Node

元Meshを入力にしたNodeと、別の出力Meshを作ります。元Meshは残り、NodeのParameterを
変更すると再計算されます。

利用前に AutoRemesher を含むMaya C++ Pluginをビルドしてください。Meshを1つ選択し、
option windowでTarget Countなどを設定して実行します。

Node作成は一括Transactionを持たないため **要バックアップ**です。UVやSkin Weightは
転送されません。

## 表面を滑らかにする

### Volume Preserving Smoothing

選択Meshを滑らかにし、閉じたMeshでは元のVolumeへ近づけます。Mesh、Vertex、Edge、Faceの
いずれかを、1つのMesh内で選択して実行します。Hard Edge、Crease、選択Edgeは輪郭として
保持されます。**Undo 1回**です。

利用前に `ywta_mesh_smoothing.dll` とMaya Pluginが必要です。

### Volume Smooth Brush

> [!WARNING]
> 現在、Maya APIの `MPoint` / `MFloatPoint` 型不一致により操作できない既知の問題があります。
> 修正されるまでは使用せず、`Volume Preserving Smoothing` を使ってください。
