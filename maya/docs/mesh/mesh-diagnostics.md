# Mesh Diagnostics

共有mesh coreで入力を変更せず診断し、修正対象のcomponentを選択します。

## 使い方

1. 診断するMeshを1つ選択します。
2. `YWTA > Mesh > Mesh Diagnostics...`を開きます。
3. 必要なら`Area Epsilon`を調整します。
4. 選択したい分類のボタンを押します。

Zero-area Faces、Duplicate Faces、3面以上のNon-manifold Edges、Winding Conflicts、
Bow-tie Vertices、閉じたBoundary Loopsを個別に選択できます。診断はread-onlyで、選択以外の
sceneデータを変更しません。実行後はIn-View Messageに全問題数とboundary数を表示します。

## 制約

- 1回に1つのMeshを診断します。
- Boundaryは各頂点のboundary次数が2の閉ループだけを返します。分岐したboundaryは
  non-manifold / bow-tie分類を先に確認してください。
- 自動修復は行いません。
