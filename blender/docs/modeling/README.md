# Modeling

[← Manual](../README.md)

Meshの形を作り直したり、表面を整えたりするツールです。

## Hair TubeをCurveで編集する

[Hair Tube Curve Cage](hair-tube.md)は、4-sided tubeから4本のCurveと別Meshを作ります。
Curveを編集したあと、密度を変えてMeshを再生成できます。

## Topologyを作り直す

[AutoRemesh](autoremesh.md)は、選択MeshからQuad主体の別Objectを生成します。元Objectは
残るため、結果を比較してから採用できます。

## 表面を滑らかにする

[Volume Preserving Smoothing](volume-smoothing.md)には、選択頂点へ一括適用する操作と、
Viewport上で局所的に塗るBrushがあります。
