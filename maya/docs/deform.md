# Deform

メニューは `YWTA > Deform` です。Skin JSON の Direct は同一 topology、Transfer は別 topology
向けです。JSON/temporary clipboard はファイル書き込みなので Maya Undo では戻りません。適用
操作は多くが単一 Undo ですが、下記の Legacy 項目は作業コピーを推奨します。

## Skin weight の保存と復元

| コマンド | 準備と最小手順 | 成功確認 / 安全 |
| --- | --- | --- |
| `Save Skin Weights` | skinned mesh を1つ以上選択し保存先を指定 | JSON の topology fingerprint/influence が保存される。**シーン変更なし / ファイル書き込み** |
| `Load Skin Weights (Same Topology)` | 保存 JSON と同一 topology の mesh を選択 | 頂点数だけでなく face connectivity が一致し、weights が復元。**Undo** |
| `Load Skin Weights to Selected Vertices` | 同一 topology mesh と復元対象 vertex を選択 | 選択 vertex だけ値を確認。locked influence/不一致は編集前拒否。**Undo** |
| `Transfer Skin Weights (Configured)` | source JSON と target mesh を選択 | Transfer Options の方式で別 topology へ転送。**Undo**。unit/up axis 不一致は拒否 |
| `Skin Transfer Options...` | 方式を `closestPoint` / `rayCast` / `closestComponent` から選択 | 次回の Configured 処理へ保存。シーン変更なし |

複数 mesh の Save は選択順で連結した virtual mesh archive です。Direct Load の適用先も同じ
連結順の1 mesh にしてください。別 topology は Transfer を使います。適用後は skinCluster の
influence と数頂点の weight 合計を確認してください。

## Temporary Skin Clipboard

- `Save Temporary Skin Weights`: 選択 mesh を一時 JSON へ保存（**シーン変更なし / ファイル書き込み**）。
- `Load Temporary Skin Weights (Direct)`: 同一 topology へ復元（**Undo**）。
- `Transfer Temporary Skin Weights (Configured)`: 一時 JSON を configured 方式で別 topology
  へ転送（**Undo**）。

一時データはユーザー単位で Maya 再起動後も残るため、別案件へ誤適用しないよう名称と scene
を確認します。

## Vertex weight

### `Copy Vertex Weights` / `Copy Average Vertex Weights`

1頂点、または複数頂点の平均 weight を永続 clipboard へコピーします（**シーン変更なし /
ファイル書き込み**、
clipboard 書込は Undo 外）。同じ influence identity を持つ target を用意してください。

### `Paste Vertex Weights`

コピー済み weight を選択 vertex へ貼り付けます。locked influence や 0–1 外の入力は拒否。
適用は **一括 Undo** です。貼り付け後に component と weight editor で値を確認します。

### `Average Vertex Weights`

選択 vertex の weight を平均し、全選択へ適用します。lock/remainder の再配分が曖昧な場合は
編集前に拒否されます。**Undo**。

### `Add Selected Skin Influences`

joint を選択し、選択 mesh の skinCluster へ weight 0 で追加。既存 weight は変更しません。
**Undo**。既存 skinCluster と global lock 状態を確認します。

### `Remove Selected Unused Influences`

選択 joint のうち未使用かつ unlocked の influence だけを削除します。削除対象を UI で確認し、
**Undo** で戻します。使用中／locked influence は保護されます。

### `Mirror Skin Weights +X to -X` / `Mirror Skin Weights -X to +X`

world YZ 面を境に指定方向へ mirror。左右の joint 名、対称位置、locked influence を事前確認し、
実行後に左右 vertex の weight を比較します。**Undo/Redo** 付きで、locked influence がある
場合は拒否されます。

### `Smooth Selected Skin Weights` と option box

選択 component の隣接頂点平均を適用します。option box で strength と iterations を設定。
局所範囲を小さく試し、weight sum と境界を確認します。**Undo**。lock influence を尊重し、
曖昧な再配分は拒否します。

### `Remove Unused Skin Influences` と option box

選択 mesh の全 output geometry を走査し、未使用で unlocked の influence を削除します。option
box で未使用判定 threshold と locked 保護を設定。削除一覧を確認して **単一 Undo**。global
lock や参照 skin は作業コピーで確認します。

## Skinned mesh topology

### `Combine Skinned Meshes`

複数 skinned mesh を選び、元 mesh を残して正確な頂点/face/influence mapping の新 mesh を作成。
実行時の joint/mesh 評価姿勢が新 skinCluster の bind state になるため、正本の rest/bind frame
へ移動してから実行します。**Undo** で出力を削除できます。補助 transform は複製せず、locked
source influence や topology fingerprint 不一致は拒否されます。

### `Separate Skinned Mesh Shells`

shell を含む skinned mesh を選び、元を残したまま shell ごとの新 mesh を作成します。vertex/face
mapping で UV、normal、color set、material、weight、bindPreMatrix を転送します。**Undo**。
出力名と namespace、animation 中の変形を確認してください。

## Shape / deformer

### `Transfer Shape` と option box

source shape と target mesh を選択して shape を転送。option box の方式・許容値を確認し、結果
の vertex delta を比較します。実装は Maya DG/mesh を変更しますが、古い経路のため **Legacy /
limited** として作業コピーを使い、単一 transaction を前提にしません。外部ファイルは変更しません。

### `Duplicate Skinned Mesh`

skinned mesh を選択して複製します。現在の実装は元の名前の mesh を削除／置換し、dagPose を
再構築する場合があります。非破壊 duplicate ではありません。必ず scene copy を作り、結果の
skinCluster、dagPose、animation を確認してください。**Developer-only / destructive**、成功後の
置換は Maya Undo だけに頼らず元 scene を保持します。

### `Bake Deformer to Blendshape`

deformer 適用結果を BlendShape target へ bake。source と target、frame/評価状態を確認し、
作成された blendShape と入力 deformer を検証します。**Legacy / limited**（全操作を単一
transaction で戻せる保証なし）。実行前に scene copy、実行後に不要 deformer の扱いを手動確認。

### `Set Keyframe Blendshape Per Frame`

指定範囲を frame ごとに評価して blendShape key を作成します。範囲と現在の time unit を確認。
大量 key を生成し、ファイルサイズと scene 性能へ影響します。**Legacy / limited**、作業コピーで
実行し、必要なら生成 animCurve を手動削除します。

### `BlendShape Target Renamer`

BlendShape target 名を一覧で変更します。対象 blendShape と新名称の衝突を確認して Apply。
名前変更はノード／attribute に影響し、既存 pipeline が名前参照している場合があります。
**Legacy / limited**。適用前に scene を保存し、結果を Channel Box と downstream 接続で確認します。
