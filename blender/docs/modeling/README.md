# Modeling

[← Manual](../README.md)

Meshの形を作り直したり、表面を整えたりするツールです。

## Hair TubeをCurveで編集する

[Hair Tube Curve Cage](hair-tube.md)は、4-sided tubeから4本のCurveと別Meshを作ります。
Curveを編集したあと、密度を変えてMeshを再生成できます。

## Topologyを作り直す

[AutoRemesh](autoremesh.md)は、選択MeshからQuad主体の別Objectを生成します。元Objectを
非表示Collectionへ保持し、生成Objectを選んで設定を変えながら再生成できます。

## 表面を滑らかにする

[Volume Preserving Smoothing](volume-smoothing.md)には、選択頂点へ一括適用する操作と、
Viewport上で局所的に塗るBrushがあります。
