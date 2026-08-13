# Hair Tube Curve Cage

[← Mesh](README.md)

Hair Tube Curve Cageは、髪束などの細長いquad tubeを、断面頂点ごとの編集可能なCurve Cageと
別Meshへ変換するMayaツールです。元Meshを残したままCurveでシルエットを調整し、長手方向の
分割数を変えて再生成したり、複数LODを一括生成したりできます。

## できること

- 3-sided以上のquad tubeから、断面頂点数と同じ本数のdegree 1 NURBS Curveを作る
- CurveのCV編集後に、任意の`Segments`でHair Tube Meshを再生成する
- 同じCurve Cageから複数密度のLOD Meshを一括生成する
- UV、face-vertex color、Material、Skin Weightを元Meshから補間する
- 4-sided tubeでは、rootまたはtipにある1枚のquad capを保持する

このツールは髪カード、開いた板ポリゴン、分岐した髪束をtubeへ変換するツールではありません。
入力は、すでに長手方向がquadでつながったtubeである必要があります。

## 開く場所と選択条件

- **Menu:** `YWTA > Mesh > Hair Tube Curve Cage...`
- **Create:** 元tubeのroot断面を囲む閉じたedge loopを1つだけ選択
- **Rebuild:** このツールが生成したHair Tube Meshを1つだけ選択
- **LOD:** このツールが生成したHair Tube Meshを1つだけ選択
- **Undo / Redo:** Create、Rebuild、LOD一括生成は、それぞれ1回の操作

選択したedge loopがrootになります。反対側を選ぶとtubeの進行方向も逆になります。rootとtipを
意図どおり扱いたい場合は、髪の生え際側のloopを選択してください。

## 入力Meshの条件

実行前に次を確認してください。

- 断面が3頂点以上で、すべての断面の頂点数が同じ
- rootからtipまでの側面がquadだけで構成されている
- 分岐、途中のcap、non-manifold edge、重複面、自己交差がない
- 選択したroot loopが1つの閉ループで、別Meshのedgeを含まない
- capを保持する場合は4-sided tubeのrootまたはtipにquad faceが1枚だけある
- Skin Weightを転送する場合はskinClusterが1つだけで、各生成位置のweight合計が0にならない
- 使用中のUV setに未割り当てcornerがない

## 初回準備

共有core DLLが必要です。開発checkoutではリポジトリのルートで次を実行します。

```powershell
uvx nox -s mesh_core_tests
```

テスト成功後、`bin/windows/ywta_mesh_core.dll`が配置されます。別のDLLを使う場合は、Mayaを
起動する前に`YWTA_MESH_CORE_DLL`へ絶対パスを設定してください。

## 最短手順

1. 元tubeをComponent Modeにします。
2. 髪の生え際側にある断面のedge loopだけを選択します。
3. `YWTA > Mesh > Hair Tube Curve Cage...`を開きます。
4. `Segments`を`8`、`Fit Tolerance`を`0`のままにします。
5. `Create from Selected Root Edges`を押します。
6. 生成されたCurveのCVを動かします。
7. 生成Hair Tube Meshを1つ選択し、`Rebuild Selected Hair Tube`を押します。

生成Meshが選択され、元Mesh、生成Mesh、Curve群がすべてSceneに残っていれば成功です。

## パラメータ

### Segments

rootからtipまでを何区間に分けるかを指定します。出力断面数は基本的に`Segments + 1`です。

- 小さい値: 軽量ですが、曲がりの強い箇所が角張りやすくなります
- 大きい値: 曲線を細かく追従しますが、頂点数と自己交差検査の負荷が増えます
- 初回は`8`を基準にし、最終用途に合わせて増減してください

### Fit Tolerance

Curve Cageを滑らかな自然三次スプラインとして評価してよい最大偏差です。単位はSceneの距離単位と
同じです。

- `0`: 元tubeのrailを折れ線として再現します。迷った場合はこの値を使います
- `0`より大きい値: 三次スプラインと元の折れ線との差が指定値以内なら滑らかなfitを使います
- 差が指定値を超えた場合: 入力を変更せず、自動的に折れ線評価へ戻ります

値を大きくすると滑らかなfitが採用されやすくなりますが、元形状から離れる可能性も増えます。
小さな値から試し、生成Meshのシルエットを確認してください。

### LOD Segments

`2,4,8`のように、1以上の整数を重複なしの昇順で指定します。各値を`Segments`として使った別Meshを
一括生成します。`8,4,2`、`2,2,4`、空欄は拒否されます。

## Curve Cageを作る

1. 入力条件を満たすtubeを用意します。
2. Component Modeでroot断面のedge loopだけを選択します。
3. Options Windowで`Segments`と`Fit Tolerance`を設定します。
4. `Create from Selected Root Edges`を押します。

元Meshは変更されません。既定では次のnodeが作られます。

- 生成Mesh: `<元名>_HairTube`
- Curve: `<元名>_HairTubeRail1`、`<元名>_HairTubeRail2`、…

Curve本数は断面頂点数と同じです。生成MeshにはCurve名とcap状態が記録され、RebuildとLOD生成は
この情報を使います。生成Meshが選択されれば成功です。不適切な結果は1回のUndoで生成Meshと
Curve群をまとめて削除できます。

## Curveを編集する

各Curveはtube表面の長手方向railです。CurveのCVを移動すると、対応する断面頂点列を編集できます。

編集してよいもの:

- Curve CVの位置
- Curve transform

変更してはいけないもの:

- Curveの削除や改名
- Curve本数の変更
- degree 1以外への変更
- Curve shapeの追加

すべてのCurveは同じCV数を保ってください。構造を変更すると、生成Meshに記録されたCage情報と
一致しなくなり、fail-closedで再生成を拒否します。

## Curve編集後に再生成する

1. Curve群のCVを編集します。
2. Curveではなく、`<元名>_HairTube`を1つだけ選択します。
3. 必要に応じて`Segments`と`Fit Tolerance`を変更します。
4. `Rebuild Selected Hair Tube`を押します。

同じ名前の生成Meshが置き換わり、CurveのCV列も新しい密度へ同期されます。元入力Meshは変更されません。
UV、Color、Material、Skin Weightは再生成前のHair Tube Meshから新しいMeshへ補間されます。
Undoで再生成前へ戻り、Redoで再生成結果へ進めます。

## 複数LODを生成する

1. Curve編集後、生成Hair Tube Meshを1つだけ選択します。
2. `LOD Segments`へ`2,4,8`のように入力します。
3. 必要なら`Fit Tolerance`を設定します。
4. `Generate LODs from Selected Hair Tube`を押します。

`<生成Mesh名>_LOD2`、`<生成Mesh名>_LOD4`、`<生成Mesh名>_LOD8`のような別Meshが作られます。
LOD Meshは同じCurve Cageを参照します。すべての密度と属性転送を先に検証するため、1つでも失敗した
場合は部分的なLODを残しません。Undo / RedoはLOD群全体で1回です。

## 転送されるデータ

- 全UV setとUV seam
- face-vertex color set
- faceごとのMaterial assignment
- 1つのskinClusterと、そのInfluenceへの正規化済みSkin Weight
- root / tipのquad cap状態

Custom Normal、BlendShape、任意のdeformer履歴は転送しません。生成後に必要な履歴を設定してください。

## よくあるエラー

### 「root断面3辺以上だけを選択してください」

Objectを選択している、edgeが3本未満、複数Meshのedgeが混ざっている状態です。Component Modeで
同じMeshの閉じた断面loopだけを選び直してください。

### 「閉じたedge loopである必要があります」

選択に欠けたedgeや枝分かれがあります。loopの各頂点へ選択edgeがちょうど2本接続されるようにします。

### 「Hair Tube Curve Cage情報がありません」

元入力MeshやLOD以外のMeshを選んでいます。このツールが作成した`*_HairTube` Meshを選択してください。

### 「Curve Cageが見つかりません／構造が変わっています」

Curveを削除・改名したか、shape構造やdegreeを変更しています。Undoで戻すか、元tubeからCageを
作り直してください。

### UVまたはSkin Weightのエラー

未割り当てUV、複数skinCluster、weight合計0を検出すると、属性を欠落させず処理全体を拒否します。
元Mesh側を修正してから再実行してください。

### zero-area／inverted quad／自己交差

Curveが交差している、断面が潰れている、`Segments`が形状に合っていない可能性があります。直前の
Curve編集を戻し、断面を開いてから再実行してください。

## Known Limitations

- 分岐、triangle側面、途中のcap、non-manifold、自己交差を含む入力は拒否します。
- cap保持は4-sided入力のroot / tipにある1枚のquadだけです。N-sided capには未対応です。
- Curve Cageのrail追加・削除やtopology編集には対応しません。
- Rebuild時にCurveは新しい密度へ作り直されるため、Curveへ追加した独自shape属性や接続は保持しません。
- 極端に大きい`Segments`では生成と品質検査の時間が増えます。
