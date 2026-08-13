# Deform ツール

[← ツールガイドへ戻る](README.md)

メニュー: `YWTA > Deform`

## Skin Weight をファイルで移す

同じトポロジへ戻す場合は Direct、異なるトポロジへ移す場合は Transfer を使います。

| ツール | 選択するもの | 結果 |
| --- | --- | --- |
| `Save Skin Weights` | Skinned Meshを1つ以上 | WeightをJSON保存。**シーン変更なし / ファイル保存** |
| `Load Skin Weights (Same Topology)` | 保存時と同じトポロジのMesh | 全頂点へ復元。**Undo 1回** |
| `Load Skin Weights to Selected Vertices` | 同じMeshの復元したい頂点 | 選択頂点だけ復元。**Undo 1回** |
| `Transfer Skin Weights (Configured)` | 転送先Mesh 1つ | 保存形状から別トポロジへ転送。**Undo 1回** |
| `Skin Transfer Options...` | なし | `closestPoint` / `rayCast` / `closestComponent` を設定 |

複数Meshを一度に保存すると、選択順で1つの仮想Meshとして記録されます。同じ構成へ戻す
用途で使い、別形状には Transfer を使ってください。

### 一時Skin Weight

- `Save Temporary Skin Weights` — 一時JSONへ保存。**シーン変更なし / ファイル保存**
- `Load Temporary Skin Weights (Direct)` — 同じトポロジへ復元。**Undo 1回**
- `Transfer Temporary Skin Weights (Configured)` — 別トポロジへ転送。**Undo 1回**

一時データはMayaを再起動しても残ります。別のAssetへ誤適用しないよう注意してください。

## 選択頂点のWeightを編集する

- `Copy Vertex Weights` — 1頂点のWeightをコピー
- `Copy Average Vertex Weights` — 複数頂点の平均Weightをコピー
- `Paste Vertex Weights` — 選択頂点へ貼り付け。**Undo 1回**
- `Average Vertex Weights` — 選択頂点を同じ平均値にする。**Undo 1回**

コピー先は永続Clipboardです。コピー操作はシーンを変更しませんが、Maya Undoでは
Clipboardの内容を戻せません。

## Influence を整理する

- `Add Selected Skin Influences` — 選択JointをWeight 0で追加。**Undo 1回**
- `Remove Selected Unused Influences` — 選択した未使用Jointだけ削除。**Undo 1回**
- `Remove Unused Skin Influences` — Mesh全体の未使用Influenceを削除。**Undo 1回**

`Remove Unused Skin Influences` の option box では判定Thresholdと、Lock済みInfluenceを
保護するかを設定できます。

## Weight をMirror・Smoothする

- `Mirror Skin Weights +X to -X`
- `Mirror Skin Weights -X to +X`
- `Smooth Selected Skin Weights`

MirrorはWorld YZ面を基準にします。左右のJoint名と位置を確認してから実行してください。
Smoothのoption boxではStrengthとIterationsを設定できます。いずれも **Undo 1回**です。

## Skinned Mesh を結合・分離する

### Combine Skinned Meshes

複数のSkinned Meshから、Weightを保った新しい結合Meshを作ります。元Meshは残ります。
実行時の姿勢が新しいBind状態になるため、正しいRest / Bind Frameへ戻してから実行します。
**Undo 1回**です。

### Separate Skinned Mesh Shells

1つのSkinned MeshをShellごとに分け、UV、Normal、Color、Material、Weightを転送します。
元Meshは残ります。**Undo 1回**です。

### Duplicate Skinned Mesh

> [!CAUTION]
> 名前に反して、単純な非破壊Duplicateではありません。現在の実装は元の名前のMeshを
> 削除・置換し、`dagPose` を再構築する場合があります。必ずScene Copyで実行してください。

## Shape / Deformer を処理する

以下は従来処理で、一括Undoや失敗時の復元が保証されていません。すべて
**要バックアップ**です。

- `Transfer Shape` — SourceからTargetへ頂点形状を転送。option boxで方式を設定
- `Bake Deformer to Blendshape` — Frameごとの変形をBlendShape TargetへBake
- `Set Keyframe Blendshape Per Frame` — TargetごとにFrame Keyを作成
- `BlendShape Target Renamer` — BlendShape Aliasを検索・置換

Bake系は大量のTargetやKeyを作ることがあります。短いFrame範囲で試してから本番Sceneへ
適用してください。
