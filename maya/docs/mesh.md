# Mesh

メニューは `YWTA > Mesh`。頂点ロックは選択状態だけを変更し、merge/remesh/smoothing は
メッシュを変更します。ネイティブ plugin が見つからない場合は処理を続行せず、Maya 2024 の
ビルド済み plugin を用意してください。

## 頂点ロック

### `Lock Selected Vertices` / `Unlock Selected Vertices`

component mode で vertex を選択し、Lock または Unlock を実行します。ロックされた vertex は
後続の編集で保護されます。geometry は変わりませんが、vertex 属性は変更されます。単一
transaction や失敗時 rollback を持たない **Legacy / limited** 操作なので、まず少数の頂点で
試し、通常の Maya Undo で戻ることを確認してください。頂点を選んでいない場合の事前検証も
ないため、必ず polygon vertex を選択してから実行します。

## Merge と skin

### `Merge Objects and Skinning`

複数 transform を選択すると geometry を merge し、階層から joint を作成して Bind Skin します。

- **準備**: 同じ asset の mesh だけを選択し、必要な rest pose を保存。
- **最小手順**: 選択して実行、生成された joint hierarchy と skinCluster を確認。
- **安全**: **Legacy / limited**。元 object の扱い、bind 状態、階層変更を scene copy で確認し、
  単一 transaction/rollback を仮定しないでください。

## AutoRemesher

### `AutoRemesher Node`

選択 mesh を入力に、オプション（target density 等）を設定して別 output object を作るノードを
追加します。`external/autoremesher` submodule と Maya plugin build が必要です。

- **最小手順**: mesh を選択 → options → Create → output mesh の topology/UV を確認。
- **安全**: node/output の作成は **Legacy / limited**。元 mesh を保持しますが、ノードを削除する
  操作や再計算を含めて作業コピーで確認してください。キャンセル、UV/weight transfer、
  Blender の擬似非破壊化は未実装（TODO）です。

## Volume Preserving Smoothing

### `Volume Preserving Smoothing`

選択 mesh を HC 方式で smoothing し、閉メッシュの volume を補正します。

- **準備**: 頂点 lock/edge boundary と smoothing 設定を確認。閉 mesh で体積評価が有効です。
- **最小手順**: mesh を選択 → 実行（必要な native/python plugin が自動 load されます）。
- **確認**: vertex position、volume、境界が意図どおりであること。
- **安全**: `VolumeSmoothingCommand` は座標の前後を保持する undoable command で、**1回 Undo**
  できます。失敗時は変更を残しません。プラグイン未配置や topology 不正は実行前に解決します。

### `Volume Smooth Brush`

viewport をドラッグして局所 smoothing（半径は object-space）を行う brush context です。通常は
stroke 単位で **Undo** になりますが、現在 `MPoint`/`MFloatPoint` TypeError の既知 blocker が
あり、利用不可として扱います。修正確認までは本番で実行せず、代わりに上記の全体 smoothing を
使用してください。
