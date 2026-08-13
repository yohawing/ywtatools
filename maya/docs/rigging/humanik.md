# HumanIK Auto Setup

選択したJoint階層から、限定的なHumanIK Characterを作成します。

## Reference

- **Menu:** `YWTA > Rigging > HumanIK Auto Setup`
- **Selection:** CharacterのRoot Joint

## Usage

Root Jointを1つだけ選択して実行します。sceneを変更する前に、選択数と階層内の
Hip/Pelvis候補を読み取り専用で検証します。候補がない場合や複数あって曖昧な場合は
fail-closedで停止し、`create_character`やHumanIK MELは呼び出しません。

検証に成功すると、階層から一意に解決したHip/PelvisをHumanIK Characterへ割り当てて
Lockします。途中でHipを一時選択しますが、成功・失敗にかかわらず実行前のJoint選択へ
戻します。Character作成後のMEL処理全体をtransactionとして戻す機能はありません。

## Assignment JSON

`ywta.rig.humanik.load_character_definition()` は、現在のHumanIK Characterへversioned JSONの
slot assignmentを適用します。ファイル全体の検証後に全slot IDと全target Jointを先に解決し、
存在しないtarget、Jointでないtarget、曖昧な短名が1件でもあればsceneを変更しません。解決した
targetはlong DAG pathへ正規化し、assignmentはslot順に適用します。

```json
{
  "format": "ywta.humanik-assignment",
  "version": 1,
  "assignments": [
    {"slot": "Hips", "target": "character:Hips"},
    {"slot": "LeftArm", "target": "character:LeftArm"}
  ]
}
```

`slot` と `target` は空でない文字列、`slot` は一意です。未知のfieldやversionは受理しません。
`target` はJSON契約ではopaque identifierとして扱います。MayaアダプターでJointへ解決しますが、
bind/rest poseの証明は後段のbuilderが担当します。旧形式の
`{"Hips": {"target": "character:Hips"}}` も読み込み時にversion 1へ正規化します。

`ywta.rig.humanik_assignment.preview_merge(base, *overrides)` は、左から順にlayerを
重ねたversion 1 assignmentと、baseからの差分を返すMaya非依存の関数です。
差分はslot順で、`added` / `changed` / `unchanged` を持ちます。削除semanticsはなく、
同一slotは後のlayerが優先されます。全layerを厳密に検証してから結果を生成し、
入力データは変更しません。

## Character Builder API

`ywta.rig.humanik.create_character_definition(assignment_data, name_hint)` は、version 1または
旧形式のassignmentから、新しいHumanIK Characterを作成します。空のassignment、未知のslot、
存在しないtarget、Jointでないtarget、曖昧な短名は、Character作成前に拒否します。

検証後はslot名順に割り当て、各slotを`hikGetSkNode`で読み戻して、期待するlong DAG pathと
完全一致することを確認します。このAPIはcurrent Characterの変更、Definition UIの更新、Lockを
行いません。割り当てまたはreadbackに失敗した場合は、このAPIが作成したCharacterだけを削除し、
sceneから消えたことも確認します。`HumanIkCharacterCreationError`の`creation_error`と
`cleanup_error`で、元の失敗とcleanupの失敗を個別に確認できます。

## Known Limitations

汎用的な全身自動マッピングではありません。Hip / Pelvis中心の限定的な設定で、Character名も
固定されています。bind/rest poseの検証、接続復元、UI拡張はこの機能の責務外です。

HumanIK MELへの依存、Character/Sourceの接続・復元、bind/rest poseの検証、Bakeは未実装です。
保存済みSceneのコピーで使用してください。
