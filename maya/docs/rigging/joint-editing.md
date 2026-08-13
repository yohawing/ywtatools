# Joint Editing

Jointの作成、挿入、向き、Mirror、複製を行います。

## Reference

- **Menu:** `YWTA > Rigging`
- **Selection:** 操作対象のJointまたは配置基準にするObject
- **Undo:** 個別メニューは1回。Joint Edit Tools内の従来操作は操作ごとに異なります

## Joint Edit Tools

`Joint Edit Tools`は、Jointの作成、挿入、Side、Local Rotation Axis、Orientなどをまとめた
ウィンドウです。Jointを選択してウィンドウを開き、一度に1つの操作を実行します。

ウィンドウ内には新しい処理と従来処理が混在しています。ウィンドウ全体を1回のUndoで
戻せるとは限らないため、保存済みSceneで使用してください。

## Creating and Editing Joints

**Create Joint** — 選択範囲の中心へJointを1つ作成します。何も選択していない場合は
原点へ作成します。

**Insert Joints Between Selected...** — 直接つながった親子Jointの間へ、1～99本のJointを
均等に挿入します。

**Orient Selected Joints to Children** — +X軸が子Jointを向くようにJoint Orientを設定します。

**Duplicate Joint Hierarchy...** — 選択したRoot Joint以下を、Find / Replaceした名前で
複製します。

**Mirror Joint Hierarchy (Static YZ)** — Joint階層をWorld YZ面で反転し、反対側の静的な
階層を作成します。名前には`L/R`、`Left/Right`、`lf/rt`のいずれかが必要です。

**Joint Size Tools** — 選択したJoint階層、またはScene内の全Jointの表示半径を変更します。

## Notes

InsertとOrientは、Skin、Constraint、IK、Animation、Lockがある階層を変更しません。
条件を満たさない場合は、Sceneを編集する前に処理を中止します。

`Freeze to offsetParentMatrix`は、選択したTransformの姿勢を`offsetParentMatrix`へ移します。
既存の接続やOPMを含むRigでは一括復元が保証されないため、Sceneのコピーで使用してください。
