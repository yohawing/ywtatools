# Hair Tube Curve Cage

4-sided hair tubeを、編集可能な4本のNURBS Curveと別Meshへ変換します。Curveを動かした
あと、長手方向の分割数を変えてMeshを再生成できます。

## Reference

- **Open:** `YWTA > Mesh > Hair Tube Curve Cage...`
- **Create selection:** tubeのroot断面を構成する4辺だけ
- **Rebuild selection:** このツールが生成したHair Tube Meshを1つ
- **LOD selection:** このツールが生成したHair Tube Meshを1つ
- **Undo / Redo:** Yes。CreateまたはRebuild全体が1回の操作です

## 初回準備

リポジトリのルートで共有coreをビルドします。

```powershell
uvx nox -s mesh_core_tests
```

テスト成功後、`bin/windows/ywta_mesh_core.dll`が配置されます。別のDLLを使う場合は、
Maya起動前に`YWTA_MESH_CORE_DLL`へ絶対パスを設定します。

## Curve Cageを作る

1. 全区間がquad 4面で構成されたopen tubeを用意します。
2. Component Modeで、根元の四角形を囲む4辺だけを選択します。
3. `YWTA > Mesh > Hair Tube Curve Cage...`を開きます。
4. `Segments`を長手方向の分割数に設定します。
5. `Create from Selected Root Edges`を押します。

元Meshは変更されません。`<元名>_HairTube`と4本のdegree-1 Curveが作られ、生成Meshが
選択されれば成功です。結果が不適切なら1回のUndoでMeshと4 Curveをまとめて削除できます。

UV seam、face-vertex color、Material assignment、Skin Weightはsource mappingで補間されます。
Skin Weightは生成頂点ごとに正規化され、同じInfluenceで新しいskinClusterを作ります。
未割り当てUV、複数skinCluster、weight合計0などは変更前にfail-closedで拒否します。

## Curve編集後に再生成する

1. 4本のCurveのCVを移動します。CV数、degree、Curve名は変更しません。
2. 生成されたHair Tube Meshを1つ選択します。
3. 必要なら`Segments`を変更します。
4. `Rebuild Selected Hair Tube`を押します。

生成Meshだけが置き換わり、元MeshとCurveは残ります。Undoで再生成前のMeshへ戻り、Redoで
再生成結果へ進めます。

## 複数LODを生成する

1. Curve編集後、生成されたHair Tube Meshを1つ選択します。
2. `LOD Segments`へ`2,4,8`のように重複なしの昇順で入力します。
3. `Generate LODs from Selected Hair Tube`を押します。

同じCurve Cageから密度ごとの別Meshを一括生成します。全LODを先に検証するため、途中の
密度が品質ゲートに失敗しても部分出力を残しません。Undo/RedoはLOD群全体で1回です。

## Known Limitations

- 分岐、cap、triangle、non-manifold、自己交差を含む入力はfail-closedで拒否します。
- Custom Normal、BlendShapeは生成Meshへ転送しません。
- 4本のCurveは同じCV数とdegree 1を保つ必要があります。
- 極端に大きい`Segments`では自己交差検査の計算量が増えます。
