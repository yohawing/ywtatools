# Animation Clips

選択したControlのKeyとTangentをJSONへ保存し、現在Frameから適用します。

## Reference

- **Menu:** `YWTA > Animation`
- **Selection:** Clipを保存または適用するControl
- **Range:** Time SliderのHighlight。未指定時はPlayback Range
- **Undo:** Clipの適用は1回。JSONの保存はMaya Undoの対象外

## Saving

`Save Selected Animation Clip`は保存先を選んでClip JSONを作成します。
`Save Temporary Animation Clip`はユーザー用の一時JSONへ保存します。

## Loading

**Load Animation Clip (Replace)** — Clipが占有する範囲の既存Keyを置き換えます。

**Load Animation Clip (Place)** — 範囲を削除せず、ClipのKeyを配置します。同じ時刻のKeyは
更新されることがあります。

**Load Animation Clip (Insert)** — 対象Controlの後続Keyを後ろへ移動してからClipを配置します。

**Load Animation Clip to Selected (Replace)** — 現在選択しているControlだけへReplaceします。

**Load Temporary Animation Clip (Configured)** — 一時Clipを保存済みのOption設定で適用します。

`Load Animation Clip (Configured)`は、Option Boxで保存したMode、Selected-only、Anchor設定を
使用します。

## Notes

Constraint駆動や非KeyableのChannelは変更されません。SceneとClipのUnitが異なる場合は
自動変換しません。Insertは、解決されたControlの開始Frame以降にあるKeyをまとめて移動します。
