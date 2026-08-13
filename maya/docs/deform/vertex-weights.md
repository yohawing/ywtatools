# Vertex Weights

選択頂点のSkin WeightをCopy、Paste、Average、Mirror、Smoothします。

## Reference

- **Menu:** `YWTA > Deform`
- **Selection:** Skinned Meshの頂点
- **Undo:** 編集操作は1回

## Copy and Paste

**Copy Vertex Weights** — 1頂点のWeightを永続Clipboardへコピーします。

**Copy Average Vertex Weights** — 複数頂点の平均WeightをClipboardへコピーします。

**Paste Vertex Weights** — ClipboardのWeightを選択頂点へ適用します。

ClipboardはMayaを再起動しても残り、内容の変更はMaya Undoでは戻りません。

## Average

`Average Vertex Weights`は、選択頂点のWeightを平均し、全選択頂点へ同じ値を設定します。

## Mirror

- `Mirror Skin Weights +X to -X`
- `Mirror Skin Weights -X to +X`

World YZ面を基準に、指定した方向へWeightをMirrorします。

## Smooth

`Smooth Selected Skin Weights`は、隣接頂点のWeightを使って選択範囲を滑らかにします。
Option BoxでStrengthとIterationsを設定できます。

LockされたInfluenceを変更できない場合や、残りのWeightを安全に配分できない場合は、
処理を開始しません。
