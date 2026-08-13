# Pipeline / Export

トップレベル `YWTA` の実行・書き出し機能です。シーンの Undo とファイルの rollback は別物
です。書き出し先や保存設定を確認し、重要な scene/FBX は事前に別名保存してください。

## `Run Script`

### `YWTA > Run Script`

選択した Python ファイルを現在の Maya process で実行します。

- **準備**: 内容をレビューし、対象 scene を保存。信頼できる script だけを指定します。
- **最小手順**: Open で `.py` を選ぶ → 実行 → Script Editor の出力と scene を確認。
- **安全**: **開発者専用 / 破壊的**。sandbox、Undo transaction、権限制限はありません。script は
  任意の node、ファイル、外部プロセスを変更でき、失敗時の自動 rollback もありません。

## `Batch Runner`

### `YWTA > Batch Runner`

scene ごとに子 `mayapy` を起動し、headless Maya で同じ script を処理します。scene list、script、
Save checkbox、Cancel、timeout、結果ログを UI で確認できます。

- **準備**: 入力 scene と script を保存。起動前に全 script の構文検証を通します。
- **最小手順**: scene を追加 → script を指定 → Save の必要性を明示 → Run。各 scene の結果と
  child stdout を確認。
- **保存の挙動**: Save を明示的に有効にした場合だけ、同じ directory の一時 scene へ完了後に
  保存し、成功時に元 file を原子的に置換します。Save 無効でも script 自身の file/scene 書込み
  は制限されません。
- **確認**: scene ごとの success/error、保存済み file、script が scene を rename/open していない
  ことを確認。Cancel は処理中 scene の完了を待ち、次を起動しません。hung child は既定 timeout
  後に終了して次へ進みます。
- **安全**: **開発者専用 / 破壊的**。Maya の親 process Undo はなく、子 script の副作用を
  rollback しません。必ずコピーと信頼できる script を使います。

## FBX export

### `Export Selected FBX`

選択 mesh、skinned mesh、または asset group を静的 FBX として保存します。skinned mesh だけを
選んだ場合は skinCluster の top influence root を自動追加します。

### `Export Animation FBX`

最上位 joint root を選び、time-slider highlight（未指定時は playback range）を bake して
animation FBX を保存します。chain 途中の joint は root として許可されません。

**共通手順**

1. Export 対象を選択（Animation は最上位 root だけ）。
2. 出力先 `.fbx` と range を指定。
3. FBX plugin が load され、書き出し後に対象 file を Maya/別 viewer で確認。

実装は Maya selection と FBX settings を push/pop して復元し、同じ directory の一時 FBX へ
書き出して成功時だけ置換します。失敗時は既存 target を保護します。scene の選択と FBX 設定は
復元されますが、成功した target file の上書きは Maya Undo ではありません。元 FBX を残し、
書き出し後の skeleton rename/duplicate/namespace 移動がないことも確認します。

## Documentation と reload

### `Documentation`

YWTA の `DOCUMENTATION_ROOT` をブラウザで開きます（**シーン変更なし**）。
オフラインではこのローカル [ツールカタログ](README.md) を参照してください。

### `Reload YWTA`

トップレベルの reload command は YWTA package を unload して再 import します。作業中の scene
データは通常変更しませんが、既存 module の参照が古くなったり UI state が失われることがあり
ます。未保存 scene を保存し、**開発者専用**として使用してください。より広い `Reload All
Modules` の制限は [Utility](utility.md) を参照します。
