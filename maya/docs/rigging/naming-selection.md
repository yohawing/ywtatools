# Naming and Selection

Nodeの名前を整理し、Rigに関連するJointやMeshを選択します。

## Naming

### Reference

- **Menu:** `YWTA > Rigging > Name Tools`
- **Selection:** 名前を変更するNode
- **Undo:** 1回

`Name Tools`は、連番、検索置換、Prefix / Suffix、番号付けをまとめたウィンドウです。
`Rename Chain`は互換性のために残されている入口で、同じウィンドウを開きます。

名前の衝突、曖昧なShort Name、参照Nodeがある場合は、変更前に処理を中止します。

## Selection

次のメニューはSceneを編集せず、選択だけを変更します。

- `Select Child Joints` — 選択階層の子Joint
- `Select Child Meshes` — 選択階層下の表示Mesh
- `Select Influencing Joints` — 選択Meshを変形するJoint
- `Select Influenced Meshes` — 選択Jointが変形するMesh

## Snap A to B

`Snap A to B (Position)`は、最後に選択したTransformのWorld Pivotへ、それ以前に選択した
Transformを移動します。RotationとScaleは変更しません。操作は1回のUndoで戻せます。
