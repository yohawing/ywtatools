# HumanIK Auto Assignment 出力境界

この文書は、`yw-retarget` が自動解決したHumanoid対応を、ywtatoolsのHumanIK設定へ
受け渡す境界を決定するものです。ここに記載したproducer機能やbuilderは未実装であり、
現行機能の説明ではありません。

## 採用するCLI境界

`yw-retarget convert-fbx` に、opt-inの
`--humanik-assignment-out <file>` を追加します。このflagは`--auto-profile`を必須とし、
`--auto-profile-heuristic`との併用も許可します。明示されなければ、既存の変換結果、ログ、
終了状態、生成ファイルを一切変更しません。public Rust library、C ABI、WASMへの公開は今回の
対象外です。

出力は、変換に実際に採用された`ResolvedAutoProfile`の`profile_value.humanoid_map`から
生成します。辞書ヒットとheuristic合成のどちらも同じ変換規則を通し、別の名前推測器は
追加しません。入力解決、profile検証、変換、assignment生成のいずれかが失敗した場合は、
指定先に新しいファイルを残しません。既存ファイルを置換する場合も、完成したJSONを
同一ディレクトリの一時ファイルへ書き、flush後にatomic replaceするまでは既存内容を保ちます。

## JSON契約

出力はywtatoolsが既に検証するstrictな`ywta.humanik-assignment` version 1だけです。

```json
{
  "format": "ywta.humanik-assignment",
  "version": 1,
  "assignments": [
    {"slot": "Hips", "target": "hips"},
    {"slot": "LeftArm", "target": "leftUpperArm"}
  ]
}
```

- root fieldは`format`、`version`、`assignments`だけとする
- assignment fieldは`slot`と`target`だけとし、どちらも空でない文字列とする
- HIK `slot`の昇順で決定的に並べる。同じ入力からはbyte-identicalなJSONを生成する
- 同じHIK `slot`が2回生成される場合、または複数slotが同じtargetを使う場合はfail-closedとする
- provenance、confidence、辞書entry ID、fingerprintなどをversion 1へ追加しない

producerの`target`は`humanoid_map`が保持する論理Joint名をそのまま記録するopaque identifierです。
namespaceやMaya DAG pathを推測、付加、正規化しません。

## Humanoid slotからHumanIK slotへの変換

以下を唯一の変換表とします。表にないslotは出力しません。

| `humanoid_map` slot | HumanIK slot |
| --- | --- |
| `root` | `Reference` |
| `hips` | `Hips` |
| `spine`, `spine1`, `chest` | 順に`Spine`, `Spine1`, `Spine2` |
| `neck`, `head` | `Neck`, `Head` |
| `left_shoulder`, `right_shoulder` | `LeftShoulder`, `RightShoulder` |
| `left_upper_arm`, `right_upper_arm` | `LeftArm`, `RightArm` |
| `left_lower_arm`, `right_lower_arm` | `LeftForeArm`, `RightForeArm` |
| `left_hand`, `right_hand` | `LeftHand`, `RightHand` |
| `left_upper_leg`, `right_upper_leg` | `LeftUpLeg`, `RightUpLeg` |
| `left_lower_leg`, `right_lower_leg` | `LeftLeg`, `RightLeg` |
| `left_foot`, `right_foot` | `LeftFoot`, `RightFoot` |
| `left_toe`, `right_toe` | `LeftToeBase`, `RightToeBase` |

`root`と`hips`が同じtargetを指すprofileでは、target重複として全体を拒否せず
`Reference`を省略して`Hips`だけを出力します。torsoは存在する
`spine`、`spine1`、`chest`を順序を保ったまま連続する`Spine`系slotへ詰めます。

fingerは`{side}_{digit}_{segment}`を次の規則で変換します。

- `side`: `left` → `LeftHand`、`right` → `RightHand`
- `digit`: `thumb` → `Thumb`、`index` → `Index`、`middle` → `Middle`、
  `ring` → `Ring`、`pinky` → `Pinky`
- `segment`: `01`、`02`、`03` → `1`、`2`、`3`

例として`left_thumb_01`は`LeftHandThumb1`、`right_pinky_03`は
`RightHandPinky3`になります。prefix、digit、segmentのどれかが規則外なら、そのslotは
未対応として出力しません。各fingerは`01`から連続するprefixだけを採用し、`01`なしの
`02`や、`02`なしの`03`は孤立slotとして出力しません。対応slotのtargetが不正、または
上記の`root == hips`以外で変換後にtarget重複が生じる場合は、ファイル全体を出力しません。

## Maya側builderの責務

ywtatools側の後続builderは、producerのtargetを選択中のroot Joint階層へrebindします。
検索範囲をその階層外へ広げず、namespaceを推測せず、各targetが一意のJointへ解決できない場合は
scene変更前に停止します。

`rebind_assignment_targets(root_joint, assignment_data)`は、このrebindだけを行う読み取り専用の
境界です。root自身とそのJoint子孫だけを候補とし、候補のlong DAG pathからnamespaceを除いた
leaf名を論理名として使います。assignmentのtargetは、この論理名とのcase-sensitiveな完全一致
だけを許可します。casefold、prefix、path suffix、assignment側namespaceの除去は行いません。
0件または複数件に一致するtarget、複数slotが同じlong DAG pathへ解決されるassignmentは、
全体をfail-closedにします。成功時はslot順を維持したversion 1契約を返し、targetだけをlong DAG
pathへ置換します。空assignmentでもrootの一意性は検証します。

assignment JSONを読み込めたことだけではCharacterをLockしません。全targetの解決に加えて、
使用するbind poseまたはrest poseが対象階層について証明できた後にだけHumanIK Characterへ
割り当て、Lockします。証明できない場合はfail-closedとし、部分適用や推測したposeでのLockを
禁止します。

## 実装ownershipと検証

`yw-retarget`側の実装ownershipは次に限定します。

- `crates/yw-retarget-cli/src/fbx.rs`: flag解析、依存条件、`ResolvedAutoProfile`からの変換、
  atomic write、help
- `crates/yw-retarget-cli/src/tests/humanik_assignment_out.rs`と
  `crates/yw-retarget-cli/src/tests.rs`: flagなし不変、辞書ヒット、heuristic併用、mapping、
  deterministic sort、重複拒否、失敗時no-file、atomic replaceのCLIテスト

ywtatools側では、`maya/ywta/rig/humanik_assignment.py`のstrict validatorをconsumerの正本とし、
選択rootへのrebind、bind/rest証明、Lock前のfail-closedをbuilderテストで固定します。

両repositoryで同じJSON fixtureを読むcross-contract golden testを推奨します。producer側は
byte列を固定し、consumer側はそのfixtureをstrict version 1として受理して期待するslot/targetを
得ることを検証します。これにより、Rust側のmapping変更やPython側の契約変更を片側だけで
成立させません。
