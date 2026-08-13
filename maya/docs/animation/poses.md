# Poses

選択したControlの現在値をJSONへ保存し、別のFrameやCharacterへ適用します。

## Reference

- **Menu:** `YWTA > Animation`
- **Selection:** Poseを保存または適用するControl
- **Undo:** Poseの適用とPose ID設定は1回。JSONの保存はMaya Undoの対象外

## Pose IDs

`Set Pose ID...`は、選択したControl 1つへ`ywtaPoseId`を設定します。Control名やNamespaceが
変わる可能性がある場合に使用します。

## Saving

`Save Selected Pose`は保存先を選んでPose JSONを作成します。
`Save Temporary Pose`はユーザー用の一時JSONへ保存します。

保存したいFrameへ移動し、Controlを選択して実行してください。

## Loading

**Load Pose** — JSONを選んでPoseを適用します。

**Load Pose to Selected** — JSON内のControlのうち、現在選択しているControlだけへ適用します。

**Load Temporary Pose (Configured)** — 一時Poseを、保存済みのOption設定で適用します。

`Load Pose`のOption Boxでは、Blend率とSelected-onlyを設定できます。Blendを0%にすると
値もKeyも変更されません。

## Notes

Constraint駆動、非Keyable、非対応型のChannelは変更されません。SceneとJSONのUnitが異なる
場合は、値を変換せず警告します。
