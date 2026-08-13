# Animation

メニューは `YWTA > Animation` です。Pose/Clip は JSON として保存し、現在の Maya シーンへ
適用します。保存・読み込みのファイル操作は Maya Undo では戻りません。適用前にシーンを
保存し、適用操作には **Undo** を使えるものがあります。

## Selection Sets

### `YWTA > Animation > Selection Sets`

objectSet を作成・選択し、portable JSON に書き出し／読み込みします。

- **準備**: セットにしたい transform、joint、control を選択。参照シーンの set は削除や
  reference edit を作らないため、編集対象を自分のシーンへ用意します。
- **最小手順**: ウィンドウで set 名を入力して Create/Capture、必要なら Export。別シーンで
  Import または Import to Selected を選びます。
- **確認**: 一覧からセットを選ぶと同じメンバーが Maya の選択へ戻ること。JSON の `version`
  と member 名が検証されます。
- **安全**: set の作成・削除・JSON 適用は **Undo**（Undo 無効時は拒否）。JSON はファイル
  書き込みのため別途バックアップ。同名候補や参照 set の曖昧な操作は拒否されます。

## Pose

### `Set Pose ID...`

選択した control 1つに `ywtaPoseId` を設定します。改名や namespace 変更に強い明示アドレス
です。参照 control、lock 済み／接続済み属性には設定できません。

### `Save Selected Pose` / `Save Temporary Pose`

選択 control の keyable scalar 属性を Pose JSON へ保存します。`Save Selected Pose` は保存先を
選び、`Save Temporary Pose` は Maya ユーザー用の一時 clipboard を更新します。

- **準備**: control transform を選択。現在値を保存したい frame に移動します。
- **確認**: JSON が作成され、別名の同じ control を後で解決できること。
- **安全**: シーンは変更しません（**シーン変更なし / ファイル書き込み**）。ファイルまたは一時 clipboard は
  Undo 対象外です。

### `Load Pose`、option box、`Load Pose to Selected`、`Load Temporary Pose (Configured)`

`Load Pose` は保存 JSON、`Load Temporary Pose (Configured)` は一時 JSON を読み込みます。
option box（`Load Pose` の右側の□）で Blend と Selected-only を設定し、Configured コマンド
は保存設定を使用します。`Load Pose to Selected` は現在選択中の同名 control だけへ適用します。

- **最小手順**: JSON を指定（Temporary は不要）、Blend/Selected-only を設定、現在 frame で
  実行します。enum は label で再解決され、欠落・重複候補は編集前に拒否されます。
- **確認**: 対象 control の値と key が期待値になり、0% Blend なら値も key も増えないこと。
- **安全**: 値の適用は **Undo**。JSON 読み込み・一時データの更新はファイル操作として
  別管理です。linear/angle/time unit の不一致は値を自動変換せず警告します。

## Animation Clip

### `Save Selected Animation Clip` / `Save Temporary Animation Clip`

選択 control の highlight（なければ playback range）にある key、tangent、fixed angle/weight
を Clip JSON へ保存します。一時版は file dialog を使わないユーザー clipboard です。

- **準備**: control を選択し、time slider の範囲を設定。
- **確認**: JSON の開始・終了 frame と channel 数が期待値で、後続の Load で再現できること。
- **安全**: **シーン変更なし / ファイル書き込み**。ファイル書き込みは Maya Undo 外です。

### `Load Animation Clip (Configured)`、option box

Configured は option box で保存した Mode（Replace/Place/Insert）、Selected-only、開始 offset、
anchor 設定を使います。右側の□で設定を開きます。

### `Load Animation Clip (Replace)` / `(Place)` / `(Insert)`

現在 frame を起点に適用します。

- **Replace**: clip 占有範囲の既存 key を置換。
- **Place**: 既存 key を削除せず、新しい key を配置。
- **Insert**: 解決できた control の後続 key を clip 長だけずらして挿入。

### `Load Animation Clip to Selected (Replace)`

Replace を現在選択中の control に限定して実行します。別キャラクターに同名 control がある
場合は選択 scope を明示し、候補が一意でない場合は拒否します。

### `Load Temporary Animation Clip (Configured)`

一時 clipboard を Configured 設定で適用します。Temporary であっても適用はシーン変更です。

**共通の確認と安全**: animCurve の weighted tangent mode が既存と異なる channel は副作用を
避けて skip されます。非 keyable／constraint 駆動属性は上書きしません。全 channel が欠落・
skip のときは no-op で Undo chunk を作りません。実キーがない端点の評価値 anchor は設定で
除外可能です。適用は **Undo** ですが、Clip JSON と一時 clipboard の書き込みは戻りません。
unit 不一致は警告して retime/値変換しません。

## 既知の範囲

現在は JSON 保存・適用と set 管理が中心です。thumbnail 付きライブラリ、カテゴリ検索、
mirrored pose はメニューにありません。Maya GUI の実機表示は利用者のセッションで確認して
ください。
