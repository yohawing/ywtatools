# Shapes and Deformers

Mesh Shapeを転送し、Deformer結果をBlendShapeへ変換します。

## Reference

- **Menu:** `YWTA > Deform`
- **Selection:** SourceとTargetのMesh、またはBlendShapeを持つMesh

## Tools

**Transfer Shape** — Source Meshの頂点位置をTargetへ転送します。Option Boxで転送方式を
設定できます。

**Bake Deformer to Blendshape** — Playback Rangeの各FrameでSourceの形状を評価し、Targetの
BlendShape TargetとKeyを作成します。

**Set Keyframe Blendshape Per Frame** — BlendShape TargetをFrameごとに1つずつ有効にする
Keyを作成します。

**BlendShape Target Renamer** — BlendShape Aliasを検索・置換します。Previewで対象名を
確認してからApplyします。

## Notes

これらは一括Undoと失敗時Rollbackが保証されていない従来処理です。Bake処理は多数のTargetや
Keyを作成する場合があります。短いFrame範囲とSceneのコピーで結果を確認してください。
