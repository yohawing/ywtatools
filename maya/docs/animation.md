# Animation ツール

[← ツールガイドへ戻る](README.md)

メニュー: `YWTA > Animation`

## Control の選択セットを作る

### Selection Sets

よく使うControlの組み合わせを保存し、あとからまとめて選択できます。

1. Controlを選択します。
2. `YWTA > Animation > Selection Sets` を開きます。
3. 名前を付けて `Create from Selection` を実行します。
4. 一覧から `Select Members` を押し、同じControlが選ばれることを確認します。

Setの作成とImportは **Undo 1回**。ExportしたJSONは **ファイル保存**です。
参照Setの削除や、同名候補が複数あるImportは拒否されます。

## Pose を保存・適用する

### 名前変更に強いIDを付ける

`Set Pose ID...` は、選択したControl 1つへ `ywtaPoseId` を設定します。Control名や
Namespaceが変わる可能性がある場合に使用します。設定は **Undo 1回**です。

### Poseを保存する

- `Save Selected Pose` — 保存先を選んでJSONへ保存
- `Save Temporary Pose` — ユーザー用の一時JSONへ保存

保存したいFrameへ移動し、Controlを選択して実行します。シーンは変更しませんが、
どちらも **ファイル保存**です。

### Poseを適用する

- `Load Pose` — JSONを選んで適用
- `Load Pose to Selected` — 現在選択中のControlだけへ適用
- `Load Temporary Pose (Configured)` — 一時Poseを保存済み設定で適用

`Load Pose` の option box では、Blend率とSelected-onlyを設定できます。適用後はControl値と
現在FrameのKeyを確認してください。適用は **Undo 1回**です。Blend 0%は何も変更しません。

## Animation Clip を保存・適用する

### Clipを保存する

- `Save Selected Animation Clip`
- `Save Temporary Animation Clip`

Controlを選択し、Time Sliderの範囲をHighlightして実行します。Highlightがない場合は
Playback Rangeが使われます。KeyとTangentがJSONへ保存されます。**ファイル保存**です。

### Clipを適用する

現在Frameを開始位置として、次のいずれかを実行します。

| ツール | 動作 |
| --- | --- |
| `Load Animation Clip (Replace)` | Clip範囲の既存Keyを置き換える |
| `Load Animation Clip (Place)` | 範囲を消さず、ClipのKeyを配置する |
| `Load Animation Clip (Insert)` | 後続Keyを後ろへ移動してClipを挿入する |
| `Load Animation Clip to Selected (Replace)` | 選択ControlだけへReplaceする |
| `Load Temporary Animation Clip (Configured)` | 一時Clipを保存済み設定で適用する |

`Load Animation Clip (Configured)` は、option boxで保存したMode、Selected-only、Anchor設定を
使います。適用は **Undo 1回**です。

> [!NOTE]
> Constraint駆動や非KeyableのChannelは上書きされません。SceneとClipのUnitが異なる場合も
> 自動変換せず警告します。Insertは、解決されたControlの開始Frame以降にあるKeyをまとめて
> 移動します。
