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
- 診断ボタン自体は修復を行いません。

## Safe Mesh Repair

同じwindowの`Preview Safe Repair`は、削除または反転予定のFaceだけを選択します。内容を確認後、
`Apply Safe Repair`を押すと、zero-area faceと後発duplicate faceを削除し、2面共有edgeの
windingを整合します。

適用は1回のUndo対象です。保持FaceのUV、Color、Material、Skin WeightはMayaのcomponent編集で
維持されます。元Faceから新Faceへの対応はtransformの`ywtaMeshRepairOldFaceToNew`へJSONで
保存します。3面以上の共有edgeやnon-orientableな面接続は変更せず拒否します。

## Split Mesh to Manifold

同じwindowの`Preview Split to Manifold`は、3面以上で共有されるedge fanと、複数に分かれた
vertex fanを選択するだけです。確認後に`Apply Split to Manifold`を押すと、頂点複製だけで
各fanを分離します。

face/corner順を変えず、UV、Color Set、Material、Skin Weightを元要素から復元します。元頂点の
対応はtransformの`ywtaManifoldSplitSourceVertex`へJSONで保存され、操作全体は1回のUndo対象です。
複数skinClusterまたはskinCluster以外のdeformerを持つmeshはデータ損失を避けるため拒否します。
穴は自動で埋めません。
