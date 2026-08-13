# Volume Preserving Smoothing

Meshの収縮を抑えながら、選択した表面を滑らかにします。一括処理とBrushの2通りが
あります。

## Batch Smoothing

- **Menu:** Edit Modeの `Vertex > Volume Preserving Smooth`
- **Selection:** Meshの頂点を1つ以上
- **Undo:** Yes

頂点を選択して実行し、HC、Taubin、Laplacianから方式を選びます。閉じたMeshでは
`閉メッシュの体積を保持`を利用できます。開いたMeshでは体積補正を省略します。

選択境界、hard edge、seam、crease、選択edgeを固定またはrailとして残せます。
`Mask Vertex Group`を指定すると、頂点選択の代わりにGroup weightを連続的な強さとして
使用します。

## Brush

- **Location:** Edit Modeの3D Viewport Toolbar（`T`）にある `Volume Smooth Brush`
- **Target:** 面を持つActive Mesh
- **Undo:** 1 strokeごとにYes

ToolbarでBrushを選び、表面を左ドラッグします。主な操作は次のとおりです。

- `F`: 半径
- `Shift+F`: 強さ
- Mouse Wheel: 反復回数
- `1` / `2` / `3`: Smooth / Volume / Remove Bumps
- `M`: 選択範囲のMask
- `B`: 境界固定
- `Esc` または Right Mouse: strokeを取り消す

## Requirements

リポジトリのルートで次を実行します。

```powershell
uvx nox -s mesh_smoothing_build
uvx nox -s mesh_smoothing_ffi_smoke
```

通常は`bin/windows/ywta_mesh_smoothing.dll`を使用します。別のDLLを使う場合は、Blenderを
起動する前に`YWTA_MESH_SMOOTHING_DLL`へ絶対パスを設定します。詳しくは
[Rust Components](../../../rust/README.md)を参照してください。

## Notes

一括処理は選択Meshを直接編集します。Brushはstroke開始時の座標を保持し、キャンセル時や
solver error時には開始状態へ戻します。Topologyを変更した場合はBrushを終了し、もう一度
開始してください。
