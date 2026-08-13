# YWTA Maya ツールカタログ

このページは Maya 2024 の `YWTA` メニューから到達できる機能の入口です。インストールと
初回起動は [Maya README](../README.md) を先に確認してください。ここでは、実装と
`tests/maya` のメニュー到達性テストで確認できる現在のコマンドだけを案内します。

## 安全表記

- **シーン変更なし**: シーン内のノードや属性を変更しない操作。選択変更を含むことが
  あります。ファイルへ保存する操作は、別途 **ファイル書き込み** と表記します。
- **Undo**: 実装が Maya の Undo chunk または undoable command を使う操作。実行後に
  `Ctrl+Z` で1回分を戻せます（Undo が無効な場合は操作を拒否する機能があります）。
- **ファイル書き込み**: JSON、FBX、ライブラリ等のファイル変更は Maya Undo の対象外です。
  成功した上書きは、必要なら元ファイルを別名で保存してから実行してください。
- **Legacy / limited**: 単一 transaction を持たない従来処理。専用の作業コピーで確認します。
- **開発者専用 / 破壊的**: 任意コード実行、ファイル書換え、元ノード削除など。バックアップを
  取り、信頼できる入力だけで使います。

GUI の実機 smoke をこの文書から行ったとは限りません。メニューの import/呼出し先は
単体テストで検証されていますが、各 DCC の表示状態やアセット固有結果は利用者の Maya
セッションで確認してください。

## 目的別クイックリンク

| 目的 | ガイド |
| --- | --- |
| ジョイント、constraint、control、HumanIK | [Rigging](rigging.md) |
| Skin weight、BlendShape、deformer | [Deform](deform.md) |
| Pose、animation clip、selection set | [Animation](animation.md) |
| 頂点ロック、merge、remesh、smoothing | [Mesh](mesh.md) |
| Run Script、Batch Runner、FBX | [Pipeline / Export](pipeline-export.md) |
| Scene Audit、テスト、依存関係、再読込 | [Utility](utility.md) |

## メニューの全体像

```
YWTA
├─ Animation        → animation.md
├─ Mesh             → mesh.md
├─ Rigging          → rigging.md
├─ Deform           → deform.md
├─ Utility          → utility.md
├─ Run Script       → pipeline-export.md
├─ Batch Runner     → pipeline-export.md
├─ Export Selected FBX / Export Animation FBX → pipeline-export.md
└─ Documentation
```

## 現在の leaf-menu inventory

以下は `maya/ywta/menu/core.py` と各 `menu_*.py` のラベルを、そのままの表記で列挙したものです。
option box（ラベルの右に小さな□が出る設定項目）も同じ操作の設定として各ガイドに記載します。

### Animation（[詳細](animation.md)）

`Selection Sets`、`Set Pose ID...`、`Save Selected Pose`、`Load Pose`、`Load Pose`
の option box、`Load Pose to Selected`、`Save Temporary Pose`、
`Load Temporary Pose (Configured)`、`Save Selected Animation Clip`、
`Load Animation Clip (Configured)`、その option box、`Load Animation Clip (Replace)`、
`Load Animation Clip (Place)`、`Load Animation Clip (Insert)`、
`Load Animation Clip to Selected (Replace)`、`Save Temporary Animation Clip`、
`Load Temporary Animation Clip (Configured)`。

### Mesh（[詳細](mesh.md)）

`Lock Selected Vertices`、`Unlock Selected Vertices`、`Merge Objects and Skinning`、
`AutoRemesher Node`、`Volume Preserving Smoothing`、`Volume Smooth Brush`。

### Rigging（[詳細](rigging.md)）

`Freeze to offsetParentMatrix`、`Joint Edit Tools`、`Mirror Joint Hierarchy (Static YZ)`、
`Create Joint`、`Insert Joints Between Selected...`、`Orient Selected Joints to Children`、
`Duplicate Joint Hierarchy...`、`Create at Selection Center` 配下の `Null`、`Locator`、
`Poly Cube`、`Poly Sphere`、`Poly Cylinder`、`Poly Plane`、`Constraints` 配下の
`Create Constraint...`、`Parent Constraint`、`Point Constraint`、`Orient Constraint`、
`Scale Constraint`、`Aim Constraint`、`Delete Constraints`、`Name Tools`、`Rename Chain`、
`Joint Size Tools`、`Export Skeleton`、`Import Skeleton`、
`Import Skeleton (Bake Rotate to Joint Orient)`、`Import Skeleton (Clean Joint TRS)`、
`Save Temporary Skeleton`、`Load Temporary Skeleton`、
`Load Temporary Skeleton (Clean Joint TRS)`、`Select Child Joints`、`Select Child Meshes`、
`Select Influencing Joints`、`Select Influenced Meshes`、`Snap A to B (Position)`、
`Connect Twist Joint` とその option box、`Control Creator`、`Export Selected Control Curves`、
`Import Control Curves`、`Swap Selected Control Shapes`、`Mirror Selected Control Shape`、
`Edit Selected Control CVs`、`Combine Selected Control Shapes`、`HumanIK Auto Setup`。

### Deform（[詳細](deform.md)）

`Save Skin Weights`、`Load Skin Weights (Same Topology)`、
`Load Skin Weights to Selected Vertices`、`Transfer Skin Weights (Configured)`、
`Skin Transfer Options...`、`Save Temporary Skin Weights`、
`Load Temporary Skin Weights (Direct)`、`Transfer Temporary Skin Weights (Configured)`、
`Copy Vertex Weights`、`Copy Average Vertex Weights`、`Paste Vertex Weights`、
`Average Vertex Weights`、`Add Selected Skin Influences`、`Remove Selected Unused Influences`、
`Mirror Skin Weights +X to -X`、`Mirror Skin Weights -X to +X`、`Smooth Selected Skin Weights`
とその option box、`Remove Unused Skin Influences` とその option box、
`Combine Skinned Meshes`、`Separate Skinned Mesh Shells`、`Transfer Shape` とその option box、
`Duplicate Skinned Mesh`、`Bake Deformer to Blendshape`、`Set Keyframe Blendshape Per Frame`、
`BlendShape Target Renamer`。

### Utility（[詳細](utility.md)）

`Scene Audit`、`Unit Test Runner`、`Dependency Visualizer`、`Dependencies Analyzer CLI`、
`Reload All Modules`、`Resource Browser`。

### トップレベル（[詳細](pipeline-export.md)）

`Reload YWTA`、`Run Script`、`Batch Runner`、`Export Selected FBX`、
`Export Animation FBX`、`Documentation`。

## 共通の使い方

1. まず作業シーンを保存し、破壊的・Legacy 操作はシーンのコピーで行います。
2. メニューラベルを上の目的別ガイドから探し、選択対象とオプションを確認します。
3. 実行後、ガイドにある成功確認（選択、ノード、JSON / FBX、レポート）を行います。
4. Undo の印がある操作は直後に Undo/Redo を一度試し、ファイル書き込みは別途バックアップを
   管理します。

依存するネイティブプラグインや Python パッケージがない場合、メニューが表示されても
処理を開始できません。Maya 2024 の `mayapy` とリポジトリの `requirements.txt` を用意し、
エラーを隠したまま本番シーンへ進めないでください。
