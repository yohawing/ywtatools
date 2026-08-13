# Skinned Meshes

Skinningを保ちながらMeshを結合、分離、複製します。

## Combining Meshes

### Reference

- **Menu:** `YWTA > Deform > Combine Skinned Meshes`
- **Selection:** Skinned Meshを2つ以上
- **Undo:** 1回

元Meshを残したまま、Weightを転送した新しい結合Meshを作成します。実行時のJointとMeshの
姿勢が、新しいSkinClusterのBind状態になります。正しいRest / Bind Frameで実行してください。

## Separating Shells

### Reference

- **Menu:** `YWTA > Deform > Separate Skinned Mesh Shells`
- **Selection:** 複数Shellを持つSkinned Mesh 1つ
- **Undo:** 1回

元Meshを残したまま、ShellごとのMeshを作成します。UV、Normal、Color Set、Material、Weight、
Bind Pre-Matrixが転送されます。

## Duplicating a Skinned Mesh

### Reference

- **Menu:** `YWTA > Deform > Duplicate Skinned Mesh`
- **Selection:** Skinned Mesh 1つ

## Known Limitations

`Duplicate Skinned Mesh`は単純な非破壊Duplicateではありません。現在の実装は元の名前のMeshを
削除・置換し、Scene内の`dagPose`を再構築する場合があります。Maya Undoだけに頼らず、
Sceneのコピーで使用してください。
