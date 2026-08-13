# Skeleton I/O

Joint階層をJSONへ保存し、別のSceneやNamespaceへ読み込みます。

## Reference

- **Menu:** `YWTA > Rigging`
- **Selection:** ExportではRoot Jointを1つ選択。Importでは選択不要
- **Undo:** Importは1回。JSONの保存はMaya Undoの対象外

## Export

`Export Skeleton`は、選択したRoot Joint以下の階層、Transform、Joint Orient、Limit、Label、
ユーザー属性をJSONへ保存します。

`Save Temporary Skeleton`は、ユーザー用の一時JSONへ保存します。

## Import

**Import Skeleton** — 保存された状態でJoint階層を作成します。

**Import Skeleton (Bake Rotate to Joint Orient)** — World姿勢を保ったままRotateを
Joint Orientへ統合します。

**Import Skeleton (Clean Joint TRS)** — Joint Orientへの統合に加え、Rotateを0、Scaleを1にして
作成します。

`Load Temporary Skeleton`と`Load Temporary Skeleton (Clean Joint TRS)`は、一時JSONを
同じ方法で読み込みます。

## Notes

既存Rootと衝突しないNamespaceを指定してください。Scene Unit、Angle Unit、Up Axisが
保存時と異なる場合は、既定では読み込みを中止します。
