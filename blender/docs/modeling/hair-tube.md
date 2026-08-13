# Hair Tube Curve Cage

4-sided hair tubeを、編集可能な4本のCurve Cageと別Meshへ変換します。Curveを動かした
あと、断面数を変えてMeshを再生成できます。

## Reference

- **Create:** Edit Modeの `Mesh > Create Hair Tube Curve Cage`
- **Rebuild:** Object Modeの `Object > Rebuild from Hair Tube Curve Cage`
- **LODs:** Object Modeの `Object > Generate Hair Tube LODs`
- **Selection:** tubeのroot断面を構成する4辺だけを選択
- **Undo:** Yes

## Curve Cageを作る

1. 4-sided tubeのMeshをEdit Modeにします。
2. 根元にある四角形の外周4辺だけを選択します。
3. `Mesh > Create Hair Tube Curve Cage`を実行します。
4. `Segments`で長手方向の分割数を決め、確定します。

元Meshは残り、別のHair Tube Meshと4本のpoly Curveが同じCollectionに作られます。
生成されたMeshがActive Objectになれば成功です。

## Curveから再生成する

1. 生成された4本のCurveをEdit Modeで動かします。
2. Object Modeへ戻り、生成されたHair Tube Meshを選択します。
3. `Object > Rebuild from Hair Tube Curve Cage`を実行します。
4. 必要なら`Segments`を変え、確定します。

再生成は選択したHair Tube ObjectのMesh datablockを置き換えます。元の入力Meshは
変更しません。

## 複数LODを生成する

1. Curve編集後、生成されたHair Tube Meshを選択します。
2. `Object > Generate Hair Tube LODs`を実行します。
3. `LOD Segments`へ`2,4,8`のように重複なしの昇順で入力します。

すべての密度を先に検証してから、密度ごとの別Objectを一括生成します。途中の密度が
品質ゲートに失敗した場合は何も作りません。操作全体は1回のUndo対象です。

## Requirements

`bin/windows/ywta_mesh_core.dll`が必要です。リポジトリのルートで次を実行すると、
coreのテストとDLLの準備を行えます。

```powershell
uvx nox -s mesh_core_tests
```

別のDLLを使う場合は、Blenderを起動する前に`YWTA_MESH_CORE_DLL`へ絶対パスを設定します。

## Known Limitations

- 入力は全区間が4-sided topologyである必要があります。
- rootには、4頂点で閉じた1つのedge loopを指定します。
- Cageは4本とも、1つの`POLY` splineのまま編集してください。削除、改名、spline形式の変更を
  行うと再生成できません。
- UV、Material、Vertex Group、Shape Keyは生成Meshへ転送されません。
