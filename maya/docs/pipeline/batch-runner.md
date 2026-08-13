# Batch Runner

Sceneごとに別の`mayapy`を起動し、同じPython Scriptを実行します。

## Reference

- **Menu:** `YWTA > Batch Runner`
- **Input:** `.ma` / `.mb` Fileと信頼できるPython Script

## Usage

1. `Add Scenes`でSceneを追加します。
2. 実行するScriptを入力します。
3. 上書きが必要な場合だけ`Save each scene in place`を有効にします。
4. `Run`を実行し、SceneごとのLogを確認します。

## Saving

Saveを有効にした場合だけ、処理済みSceneを同じDirectoryの一時Fileへ保存し、成功後に元Fileを
置き換えます。処理に失敗した場合、元のScene Fileは変更しません。

## Warning

Script自身が行うFile書き込みは制限されません。親MayaのUndoも利用できません。入力Sceneの
コピーと、内容を確認したScriptを使用してください。
