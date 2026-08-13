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
- 診断operator自体は修復を行いません。

## Safe Mesh Repair

同じメニューの`Safe Mesh Repair`は既定でdry-runです。`Apply Changes`を無効のまま実行すると、
削除または反転予定のFaceだけを選択します。内容を確認後、もう一度開いて`Apply Changes`を
有効にすると、zero-area faceと後発duplicate faceを削除し、2面共有edgeのwindingを整合します。

適用は1回のUndo対象です。保持FaceのUV、Color、Material、Vertex GroupはBlenderのBMesh編集で
維持されます。元Faceから新Faceへの対応はObjectの`ywta_mesh_repair_old_face_to_new`へJSONで
保存します。3面以上の共有edgeやnon-orientableな面接続は変更せず拒否します。

## Split Mesh to Manifold

`Mesh > Split Mesh to Manifold`は、3面以上で共有されるedge fanと、複数に分かれたvertex fanを
頂点複製だけで分離します。既定はdry-runで、対象edgeとvertexを選択するだけです。確認後に
`Apply Changes`を有効にして実行します。

face/corner順を変えず、UVとcorner colorをそのまま、point colorとVertex Group weightを元頂点
から複製します。元頂点の対応は`ywta_manifold_split_source_vertex`へJSONで保存され、操作全体は
Undo対象です。Shape Key付きmeshはデータ損失を避けるため拒否します。穴は自動で埋めません。
