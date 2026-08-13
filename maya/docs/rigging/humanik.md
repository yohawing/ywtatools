# HumanIK Auto Setup

選択したJoint階層から、限定的なHumanIK Characterを作成します。

## Reference

- **Menu:** `YWTA > Rigging > HumanIK Auto Setup`
- **Selection:** CharacterのRoot Joint

## Usage

Root Jointを選択して実行します。処理は階層からHipまたはPelvisを探し、HumanIK Characterへ
割り当ててLockします。

## Assignment JSON

`ywta.rig.humanik.load_character_definition()` は、現在のHumanIK Characterへversioned JSONの
slot assignmentを適用します。ファイル全体の検証後に全slot IDを先に解決し、1件でも無効なら
sceneを変更しません。assignmentはslot順に適用します。

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
`target` はこの契約ではopaque identifierとして扱い、Maya scene内の解決やbind/rest poseの証明は
後段のbuilderが担当します。旧形式の `{"Hips": {"target": "character:Hips"}}` も読み込み時に
version 1へ正規化します。

## Known Limitations

汎用的な全身自動マッピングではありません。Hip / Pelvis中心の限定的な設定で、Character名も
固定されています。

HumanIK MELへの依存、Character/Sourceの接続・復元、bind/rest poseの検証、Bakeは未実装です。
保存済みSceneのコピーで使用してください。
