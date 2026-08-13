# Run Script

Disk上のPython Scriptを、現在のMaya Processで実行します。

## Reference

- **Menu:** `YWTA > Run Script`
- **Input:** 信頼できる`.py` File

## Usage

Root Directoryを設定し、Tree内のPython FileをDouble Clickします。実行したFileはRecentへ
記録され、そこから再実行できます。

## Warning

Sandbox、Undo Transaction、失敗時のRollbackはありません。ScriptはScene、File、外部Processを
自由に変更できます。内容を確認したScriptだけを、保存済みSceneで実行してください。
