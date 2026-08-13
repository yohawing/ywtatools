# Mesh Diagnostics

共有mesh coreで入力を変更せず診断し、修正対象のcomponentを選択します。

## 使い方

1. 診断するMeshをEdit Modeにします。
2. `Mesh > Select Mesh Diagnostics`を実行します。
3. `Category`で分類を選びます。zero-areaだけは必要に応じて`Area Epsilon`を調整します。
4. 実行後、該当するFace、Edge、Vertexだけが選択されます。

分類はZero-area Faces、Duplicate Faces、3面以上のNon-manifold Edges、Winding
Conflicts、Bow-tie Vertices、閉じたBoundary Loopsです。診断はread-onlyで、選択以外の
meshデータを変更しません。結果が0件ならObject選択を維持し、Infoに全問題数とboundary数を
表示します。

## 制約

- 1回に1つのMeshを診断します。
- Boundaryは各頂点のboundary次数が2の閉ループだけを返します。分岐したboundaryは
  non-manifold / bow-tie分類を先に確認してください。
- 自動修復は行いません。
