# Hair Tube Curve Cage

[← Modeling](README.md)

Hair Tube Curve Cageは、髪束などの細長いquad tubeを、断面頂点ごとの編集可能なCurve Cageと
別Mesh Objectへ変換するBlenderツールです。元Objectを残したままCurveで形を調整し、長手方向の
分割数を変えて再生成したり、複数LODを一括生成したりできます。

## できること

- 3-sided以上のquad tubeから、断面頂点数と同じ本数のPOLY Curveを作る
- Curve編集後に、任意の`Segments`でHair Tube Meshを再生成する
- 同じCurve Cageから複数密度のLOD Objectを一括生成する
- UV、Material、POINT / CORNER Color、Vertex Groupを元Meshから補間する
- Armatureと同名のVertex Groupを正規化し、Armature Modifierを引き継ぐ
- 4-sided tubeでは、rootまたはtipにある1枚のquad capを保持する

このツールは髪カード、開いた板ポリゴン、分岐した髪束をtubeへ変換するツールではありません。
入力は、すでに長手方向がquadでつながったtubeである必要があります。

## 開く場所と選択条件

- **Create:** Edit Modeの`Mesh > Create Hair Tube Curve Cage`
- **Rebuild:** Object Modeの`Object > Rebuild from Hair Tube Curve Cage`
- **LOD:** Object Modeの`Object > Generate Hair Tube LODs`
- **Create selection:** Active Meshのroot断面を囲む閉じたedge loopを1つだけ選択
- **Rebuild / LOD selection:** このツールが生成したHair Tube MeshをActive Objectにする
- **Undo:** Create、Rebuild、LOD一括生成は、それぞれ1回の操作

選択したedge loopがrootになります。反対側を選ぶとtubeの進行方向も逆になります。rootとtipを
意図どおり扱いたい場合は、髪の生え際側のloopを選択してください。

## 入力Meshの条件

実行前に次を確認してください。

- 断面が3頂点以上で、すべての断面の頂点数が同じ
- rootからtipまでの側面がquadだけで構成されている
- 分岐、途中のcap、non-manifold edge、重複面、自己交差がない
- 選択したroot loopが1つの閉ループになっている
- capを保持する場合は4-sided tubeのrootまたはtipにquad faceが1枚だけある
- Skin Weight相当のVertex Groupを転送する場合、生成位置でbone groupのweight合計が0にならない
- 使用中のUV layerに未割り当てloopがない

## 初回準備

`bin/windows/ywta_mesh_core.dll`が必要です。開発checkoutではリポジトリのルートで次を実行します。

```powershell
uvx nox -s mesh_core_tests
```

別のDLLを使う場合は、Blenderを起動する前に`YWTA_MESH_CORE_DLL`へ絶対パスを設定してください。

## 最短手順

1. 元tubeをActive ObjectにしてEdit Modeへ入ります。
2. 髪の生え際側にある断面のedge loopだけを選択します。
3. `Mesh > Create Hair Tube Curve Cage`を実行します。
4. `Segments`を`8`、`Fit Tolerance`を`0`のまま確定します。
5. 作成されたCurveをEdit Modeにし、control pointを移動します。
6. Object Modeへ戻り、生成Hair Tube MeshをActive Objectにします。
7. `Object > Rebuild from Hair Tube Curve Cage`を実行します。

生成MeshがActive Objectになり、元Mesh、生成Mesh、Curve群が同じCollectionに残っていれば成功です。

## パラメータ

### Segments

rootからtipまでを何区間に分けるかを指定します。出力断面数は基本的に`Segments + 1`です。

- 小さい値: 軽量ですが、曲がりの強い箇所が角張りやすくなります
- 大きい値: Curveを細かく追従しますが、頂点数と品質検査の負荷が増えます
- 初回は`8`を基準にし、最終用途に合わせて増減してください

### Fit Tolerance

Curve Cageを滑らかな自然三次スプラインとして評価してよい最大偏差です。単位はSceneの距離単位と
同じです。

- `0`: 元tubeのrailを折れ線として再現します。迷った場合はこの値を使います
- `0`より大きい値: 三次スプラインと元の折れ線との差が指定値以内なら滑らかなfitを使います
- 差が指定値を超えた場合: 入力を変更せず、自動的に折れ線評価へ戻ります

値を大きくすると滑らかなfitが採用されやすくなります。小さな値から試し、生成Meshのシルエットを
確認してください。

### LOD Segments

`2,4,8`のように、1以上の整数を重複なしの昇順で指定します。`8,4,2`、`2,2,4`、空欄は拒否されます。

## Curve Cageを作る

1. 元tubeをActive ObjectにしてEdit Modeへ入ります。
2. root断面のedge loopだけを選択します。
3. `Mesh > Create Hair Tube Curve Cage`を実行します。
4. Operator Dialogで`Segments`と`Fit Tolerance`を設定し、確定します。

元Objectは変更されません。元Objectと同じCollectionへ、既定で次のObjectが作られます。

- 生成Mesh: `<元名>_HairTube`
- Curve: `<元名>_HairTubeRail1`、`<元名>_HairTubeRail2`、…

Curve本数は断面頂点数と同じです。生成MeshのCustom PropertyにはCurve名とcap状態が保存され、
RebuildとLOD生成はこの情報を使います。生成MeshがActive Objectになれば成功です。Undoすると生成Meshと
Curve群をまとめて取り消せます。

## Curveを編集する

各Curveはtube表面の長手方向railです。Curve ObjectをEdit Modeにし、control pointを移動します。

編集してよいもの:

- POLY splineのcontrol point位置
- Curve Objectのtransform

変更してはいけないもの:

- Curve Objectの削除や改名
- Curve本数の変更
- splineの追加や削除
- spline typeを`POLY`以外へ変更

すべてのCurveは1つのPOLY splineと同じcontrol point数を保ってください。構造を変更すると生成Meshの
Cage情報と一致しなくなり、fail-closedで再生成を拒否します。

## Curve編集後に再生成する

1. Curveのcontrol pointを編集します。
2. Object Modeへ戻ります。
3. Curveではなく、`<元名>_HairTube`をActive Objectにします。
4. `Object > Rebuild from Hair Tube Curve Cage`を実行します。
5. 必要に応じて`Segments`と`Fit Tolerance`を変更し、確定します。

選択したHair Tube ObjectのMesh datablockが置き換わり、Curveのcontrol point列も新しい密度へ同期されます。
元入力Objectは変更されません。属性は再生成前のHair Tube Meshから新しいMeshへ補間されます。

## 複数LODを生成する

1. Curve編集後、生成Hair Tube MeshをActive Objectにします。
2. `Object > Generate Hair Tube LODs`を実行します。
3. `LOD Segments`へ`2,4,8`のように入力します。
4. 必要なら`Fit Tolerance`を設定し、確定します。

`<生成Object名>_LOD2`、`<生成Object名>_LOD4`、`<生成Object名>_LOD8`のような別Objectが、
元Objectと同じCollectionへ作られます。LOD Objectは同じCurve Cageを参照します。すべての密度と属性転送を
先に検証するため、1つでも失敗した場合は部分的なLODを残しません。操作全体は1回のUndo対象です。

## 転送されるデータ

- 全UV layerとUV seam相当のloop値
- faceごとのMaterial assignment
- POINT / CORNER domainのColor Attribute
- 全Vertex Group
- bone名と一致するVertex Groupの正規化済みweight
- 元Objectが参照するArmature Modifier
- root / tipのquad cap状態

Shape Key、Custom Normal、Armature以外のModifierは転送しません。必要なModifierは生成後に設定してください。

## よくあるエラー

### Createメニューが実行できない

Active ObjectがMeshではないか、Edit Modeではありません。対象MeshをActiveにしてEdit Modeへ入り、
root loopを選択してください。

### 「閉じたedge loopである必要があります」

選択に欠けたedgeや枝分かれがあります。loopの各頂点へ選択edgeがちょうど2本接続されるようにします。

### Rebuild／LODメニューが実行できない

Active Objectが、このツールで作ったHair Tube Meshではありません。Curveや元入力Meshではなく、
`*_HairTube` ObjectをActiveにしてください。

### 「Curve Cageが見つからないか構造が変わっています」

Curveを削除・改名したか、spline数またはtypeを変更しています。Undoで戻すか、元tubeからCageを
作り直してください。

### UVまたはweightのエラー

未割り当てUVや、生成位置でbone groupのweight合計0を検出すると、属性を欠落させず処理全体を
拒否します。元Mesh側を修正してから再実行してください。

### zero-area／inverted quad／自己交差

Curveが交差している、断面が潰れている、`Segments`が形状に合っていない可能性があります。直前の
Curve編集を戻し、断面を開いてから再実行してください。

## Known Limitations

- 分岐、triangle側面、途中のcap、non-manifold、自己交差を含む入力は拒否します。
- cap保持は4-sided入力のroot / tipにある1枚のquadだけです。N-sided capには未対応です。
- Curve Cageのrail追加・削除やtopology編集には対応しません。
- Rebuild時にCurve splineを新しい密度へ作り直すため、splineへ追加した独自設定は保持しません。
- 極端に大きい`Segments`では生成と品質検査の時間が増えます。
