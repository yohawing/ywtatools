# Rigging

メニューは `YWTA > Rigging` です。joint、constraint、control、skeleton の編集は、明記した
ものを除き事前検証と単一 Undo を使います。参照ノード、lock、既存接続を含む入力は編集前に
拒否されることがあります。

## Transform と joint の基本操作

### `Joint Edit Tools`

`YWTA > Rigging > Joint Edit Tools` は joint の追加、挿入、side mirror、child 方向への orient、
display size などをまとめた既存ウィンドウです。対象 joint を選択して1つのボタンだけを実行し、
階層・world pose・接続を確認してください。`Add Joint`、`Mirror Joint`、`Align with Child` など
の編集は対応する上記コマンドと同じ検証経路を使うものがありますが、ウィンドウ全体を一括操作の
transactionとはみなさず、**Legacy / limited** として作業コピーで確認します。

| コマンド | 使いどころと最小手順 | 安全メモ |
| --- | --- | --- |
| `Freeze to offsetParentMatrix` | transform を選択し、現在の TRS を offsetParentMatrix へ移す | **Legacy / limited**。接続や既存 OPM を含む rig は複製シーンで確認。単一 transaction/rollback を前提にしない |
| `Create Joint` | mesh/component を選択して中心に1 joint（空選択は原点）を作成 | **Undo**。最後に選択した joint を parent にする。参照 parent は拒否 |
| `Insert Joints Between Selected...` | 隣接する親子 joint を選択し、挿入数（1–99）を指定 | **Undo**。分岐、skin/constraint/IK 接続、lock/参照 joint は拒否 |
| `Orient Selected Joints to Children` | joint 階層を選択して子方向へ +X orient | **Undo**。leaf、分岐、接続・lock のある階層は拒否 |
| `Duplicate Joint Hierarchy...` | root を選び Find/Replace 名を入力して複製 | **Undo**。joint 以外の子 DAG、参照、名前衝突を事前拒否 |
| `Mirror Joint Hierarchy (Static YZ)` | L/R、Left/Right、lf/rt token を含む root を選択 | **Undo**。world YZ の静的複製。live network ではない |
| `Joint Size Tools` | joint 階層（または UI の全 joint）を選び display radius を設定 | **Undo**。正の有限値、非参照・未lockのみ |

### `Create at Selection Center > Null / Locator / Poly Cube / Poly Sphere / Poly Cylinder / Poly Plane`

各 primitive は `YWTA > Rigging > Create at Selection Center` の leaf です。選択全体の world
bounding-box 中心（空選択は原点）へ作成します。**Undo** で作成・選択を戻せます。名前を
指定する API 経路では current namespace に依存せず、既存名や Maya 自動変換名を拒否します。

## Constraints

### `YWTA > Rigging > Constraints > Create Constraint...`

種別（Parent/Point/Orient/Scale/Aim）、Maintain Offset、Aim/Up 軸を設定します。driver を
先、driven を最後に選択し、Create を押します。Aim/Up のゼロ長・平行ベクトル、参照 node、
重複 driver、lock/animCurve 接続 channel は拒否します。作成は **Undo** です。

### `Parent Constraint` / `Point Constraint` / `Orient Constraint` / `Scale Constraint` / `Aim Constraint`

Maintain Offset がオンの既定値で作るショートカットです。driver→driven の順で選択し、実行後に
driven の constraint node と offset を確認します。作成失敗時は rollback、成功時は
**1回 Undo** です。種類や Aim / Up 軸を変える場合は `Create Constraint...` を使います。

### `Delete Constraints`

選択 transform を駆動する constraint だけを削除します。削除対象と選択を確認してから実行し、
**Undo** で戻します。参照ノード由来の編集は拒否されます。

## 命名、選択、スナップ

### `Name Tools` / `Rename Chain`

`Name Tools` は連番（`#` 桁）、検索置換、prefix/suffix、末尾番号、wildcard、namespace 保持、
親子 rename をまとめて実行します。`Rename Chain` は互換性のため残している入口で、現在は
`Name Tools` と同じウィンドウを開きます。対象を選択し、preview/検証後に Apply します。

- **確認**: 競合・曖昧な短名・参照 node がないこと、期待した full name になったこと。
- **安全**: どちらの入口も、検証成功後に **Undo/rollback**。参照を変更する rename や namespace
  自動作成は拒否します。

### Selection Navigation

以下は **シーン変更なし / 選択のみ**（ただし Snap はシーン変更）です。

- `Select Child Joints`: 選択 root の子孫 joint。
- `Select Child Meshes`: 選択階層下の表示 mesh transform。
- `Select Influencing Joints`: 選択 mesh の skinCluster influence。
- `Select Influenced Meshes`: 選択 joint を influence に持つ mesh。

複数 skinCluster/output geometry は重複除外されます。結果の選択を Outliner/viewport で確認します。

`Snap A to B (Position)` は複数 transform を「最後に選択した target」の world pivot へ位置だけ
移動します。親子順を解決して **1回 Undo**、参照 source は拒否。回転・scale は変わりません。

## Skeleton I/O

### Export

`Export Skeleton`（`YWTA > Rigging > Export Skeleton`）は選択 root から versioned JSON を保存。
**シーン変更なし / ファイル書き込み**で、JSON の変更は Undo 外です。保存後、version と joint
階層・属性が期待通りか確認します。

### Import

`Import Skeleton`、`Import Skeleton (Bake Rotate to Joint Orient)`、
`Import Skeleton (Clean Joint TRS)` は JSON を検証して namespace へ新規階層を作成します。

- **準備**: 既存 root と衝突しない namespace、同じ linear/angle unit と up axis（不一致は既定で拒否）。
- **Bake**: world 姿勢を維持して rotate を jointOrient へ統合。
- **Clean Joint TRS**: Bake に加えて joint scale=1、rotate=0 を目標にする。
- **確認/安全**: 新 root、world pose、属性を確認。作成は **単一 Undo/rollback**、既存 root・
  不正名・schema/enum 不備はシーン変更前に拒否。JSON 自体は Undo 外。

### Temporary Skeleton

`Save Temporary Skeleton` は選択 joint の top root を一時 JSON へ保存（**シーン変更なし /
ファイル書き込み**）。
`Load Temporary Skeleton`、`Load Temporary Skeleton (Clean Joint TRS)` はそれぞれ通常 import／
Clean import を一時 JSON から行います。適用は **Undo**、一時 JSON は別管理です。

## Control Creator と shape

### `Control Creator`

ウィンドウで curve primitive/library を選び、Build at Origin または Build at Selection を実行。
色変更、Smart Mirror、CV 編集、Combine を同じ UI から行えます。選択 transform/component の
world bounds を準備し、作成後に shape の表示色・visibility・接続を確認します。新規作成や
shape 編集は通常 **単一 Undo/rollback**。参照 control、子 transform を持つ source の Combine
は拒否されます。library の保存・rename・delete は JSON/ファイル操作で Maya Undo 外なので、
上書き確認とバックアップを必ず行います。

### Curve leaf commands

- `Export Selected Control Curves`: 選択 control の multi-shape curve JSON を保存（**シーン変更なし /
  ファイル書き込み**）。
- `Import Control Curves`: 保存された名前で新しい control transform を作成（**Undo**、schema/名前検証）。
- `Swap Selected Control Shapes`: transform、key、constraint を維持して shape だけ交換（**Undo**）。
- `Mirror Selected Control Shape`: side token/namespace から反対側を解決し world YZ 反転（**Undo**）。
- `Edit Selected Control CVs`: 選択 control 直下の NURBS curve CV だけを編集選択（**シーン変更なし /
  選択のみ**）。
- `Combine Selected Control Shapes`: 最後に選択した control へ world shape を結合し、他 source
  transform を削除（**Undo**だが破壊的。子 transform・参照 source は拒否）。

## Swing/Twist

### `Connect Twist Joint` と option box

driver、driven の順で選択し、option box で twist axis/weight 等を設定して network を作成。
作成後、driven が期待する twist/swing に追従するかを確認します。既存 network/plug を確認
してから使ってください。実装は Maya plugin と DG node を追加する **Legacy / limited** 操作で、
すべてを1 transactionで戻せる契約ではありません。rig のコピーで行い、必要なら node/network
を手動で削除できるよう記録します。

## HumanIK

### `HumanIK Auto Setup`

選択 character/rig を基に HumanIK を自動設定します。hip/pelvis 中心の限定的な mapping と固定
character 挙動で、汎用 retargeter ではありません。現在の環境では PyMEL import が必要で、
`ModuleNotFoundError: No module named 'pymel'` になる既知の問題があります。依存が解決しても
結果を Character Controls で確認し、作業コピーで手動修正・rollback できる状態を保ってください。

## 既知の範囲

live mirror network、汎用 mirrored pose、component blueprint などは現行メニューにありません。
各操作の implementation/test は Maya 2024 を対象とし、ここで実 GUI smoke を保証するものでは
ありません。
