# Rigging ツール

[← ツールガイドへ戻る](README.md)

メニュー: `YWTA > Rigging`

## ジョイントを編集する

### Joint Edit Tools

ジョイントの作成、挿入、向き、Side、表示軸などをまとめたウィンドウです。

1. 編集するジョイントを選択します。
2. `YWTA > Rigging > Joint Edit Tools` を開きます。
3. 一度に1つの操作だけを実行し、階層と姿勢を確認します。

ウィンドウ内には新しい安全な処理と従来処理が混在しています。Create、Insert、Mirror、
Align などを含め、ウィンドウ全体を1回の Undo で戻せるとは限りません。
**要バックアップ**として扱ってください。

### よく使うジョイント操作

| ツール | 選択するもの | 結果 |
| --- | --- | --- |
| `Create Joint` | 任意のオブジェクトやコンポーネント | 選択範囲の中心へジョイントを作成。空選択なら原点。**Undo 1回** |
| `Insert Joints Between Selected...` | 直接つながった親子ジョイント | 間に1～99本のジョイントを均等挿入。**Undo 1回** |
| `Orient Selected Joints to Children` | 子を1つ持つ未リグのジョイント階層 | +X軸を子へ向ける。**Undo 1回** |
| `Duplicate Joint Hierarchy...` | ルートジョイント1つ | Find / Replace した名前で階層を複製。**Undo 1回** |
| `Mirror Joint Hierarchy (Static YZ)` | 左右名を持つルートジョイント1つ | YZ面で反対側の静的階層を作成。**Undo 1回** |
| `Joint Size Tools` | ジョイントまたは階層 | Viewport上の表示半径を変更。**Undo 1回** |

挿入や向き変更は、Skin、Constraint、IK、Animation、Lock がある階層を事前に拒否します。
Mirror には `L/R`、`Left/Right`、`lf/rt` のいずれかの名前が必要です。

### Create at Selection Center

`YWTA > Rigging > Create at Selection Center` から、選択範囲の中心へ次を作成できます。

`Null` / `Locator` / `Poly Cube` / `Poly Sphere` / `Poly Cylinder` / `Poly Plane`

空選択では原点へ作成されます。いずれも **Undo 1回** です。

### Freeze to offsetParentMatrix

選択した Transform の現在姿勢を `offsetParentMatrix` へ移し、TRS などを整理します。
既存の接続や OPM がある Rig では想定外の結果になり得ます。単一処理としての復元保証が
ないため、**要バックアップ**です。

## Constraint を作る

driver を先、driven を最後に選択します。

- `Create Constraint...` — 種類、Maintain Offset、Aim / Up 軸を設定して作成
- `Parent Constraint`
- `Point Constraint`
- `Orient Constraint`
- `Scale Constraint`
- `Aim Constraint`
- `Delete Constraints` — 選択した Transform を駆動する Constraint を削除

ショートカット5種は Maintain Offset がオンの既定値で作成します。Aim / Up 軸などを
変えたい場合は `Create Constraint...` を使ってください。作成と削除は **Undo 1回** です。

## 名前を整理する

### Name Tools / Rename Chain

選択ノードの連番、検索置換、Prefix / Suffix、番号付けをまとめて行います。
`Rename Chain` は互換用の入口で、現在は `Name Tools` と同じウィンドウを開きます。

名前の衝突や参照ノードは変更前に拒否されます。適用は **Undo 1回** です。

## 関連ノードを選択する

次の4項目はシーンを編集せず、選択だけを変更します。

- `Select Child Joints` — 選択階層の子ジョイント
- `Select Child Meshes` — 選択階層下の表示メッシュ
- `Select Influencing Joints` — 選択メッシュを変形するジョイント
- `Select Influenced Meshes` — 選択ジョイントが変形するメッシュ

`Snap A to B (Position)` は、最後に選んだ Transform の位置へ、それ以前の Transform を
移動します。回転と Scale は変更しません。**Undo 1回**です。

## Skeleton を保存・読み込みする

### JSONへ保存

- `Export Skeleton` — 選択したルート階層を保存
- `Save Temporary Skeleton` — ユーザー用の一時JSONへ保存

どちらもシーンは変更しませんが、**ファイル保存**は Maya Undo の対象外です。

### JSONから読み込む

- `Import Skeleton` — 保存状態のまま作成
- `Import Skeleton (Bake Rotate to Joint Orient)` — Rotate を Joint Orient へ統合
- `Import Skeleton (Clean Joint TRS)` — Joint Orient へ統合し、Rotate 0 / Scale 1 で作成
- `Load Temporary Skeleton`
- `Load Temporary Skeleton (Clean Joint TRS)`

既存名との衝突がない Namespace を指定します。Scene Unit や Up Axis が保存時と異なる場合は
拒否されます。読み込みは **Undo 1回**です。

## Control Curve を作る

### Control Creator

Curve の作成、ライブラリ、色、Mirror、CV編集、Shape結合をまとめたウィンドウです。
作成やShape編集は基本的に **Undo 1回**。ライブラリの保存・改名・削除は
**ファイル保存**のため Maya Undo では戻りません。

### 個別メニュー

- `Export Selected Control Curves` — 選択CurveをJSON保存。**シーン変更なし / ファイル保存**
- `Import Control Curves` — JSONから新しいControlを作成。**Undo 1回**
- `Swap Selected Control Shapes` — Transformを残してShapeだけ交換。**Undo 1回**
- `Mirror Selected Control Shape` — 反対側ControlへYZ反転したShapeを設定。**Undo 1回**
- `Edit Selected Control CVs` — 直下のCurve CVを選択。**シーン変更なし**
- `Combine Selected Control Shapes` — 最後に選んだControlへShapeを集約し、他のTransformを削除。**Undo 1回**

## Swing / Twist を接続する

`Connect Twist Joint` は、driver、driven の順で選択し、option box で軸とWeightを設定します。
Pluginと複数のDG Nodeを作る従来処理で、既存接続を含めた一括復元は保証されません。
**要バックアップ**です。

## HumanIK を設定する

`HumanIK Auto Setup` は、Hip / Pelvis を中心に限定的なHumanIK Characterを作成します。
汎用的な全身自動マッピングではありません。

> [!WARNING]
> 現在は PyMEL が見つからず起動できない環境があります。固定Character名などの制約も
> あるため、依存解決後も作業シーンのコピーで結果を確認してください。
