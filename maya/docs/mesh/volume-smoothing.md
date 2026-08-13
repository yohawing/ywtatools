# Volume Preserving Smoothing

MeshのVolumeと輪郭を保ちながら表面を滑らかにします。

## Reference

- **Menu:** `YWTA > Mesh > Volume Preserving Smoothing`
- **Selection:** 1つのMeshに属するMesh、Vertex、Edge、またはFace
- **Undo:** 1回

## Usage

対象を選択して実行します。閉じたMeshでは、Smoothing後の形状を元のVolumeへ近づけます。
Hard Edge、Crease、選択Edgeは輪郭として保持されます。Soft Selectionは強さとして使用されます。

## Requirements

`ywta_mesh_smoothing.dll`とMaya Pluginが必要です。

## Volume Smooth Brush

`Volume Smooth Brush`は、Viewport上をDragして局所的にSmoothingするToolです。

## Known Limitations

現在、BrushにはMaya APIの`MPoint` / `MFloatPoint`型不一致があり、操作できません。
修正されるまでは通常の`Volume Preserving Smoothing`を使用してください。
