# Pipeline / Export ツール

[← ツールガイドへ戻る](README.md)

トップレベルの `YWTA` メニューにあります。

## Python Script を実行する

### Run Script

指定したFolderから `.py` を選び、現在のMaya内で実行します。実行したScriptはRecentへ
記録されます。

> [!CAUTION]
> Sandboxも自動Undoもありません。ScriptはScene、File、外部Processを自由に変更できます。
> 内容を確認した信頼できるScriptだけを、保存済みSceneで実行してください。

## 複数Sceneを一括処理する

### Batch Runner

Sceneごとに別の `mayapy` を起動し、同じPython Scriptを実行します。

1. `Add Scenes` で `.ma` / `.mb` を追加します。
2. 実行するScriptを入力します。
3. 上書きが必要な場合だけ `Save each scene in place` をオンにします。
4. `Run` を押し、Sceneごとの結果Logを確認します。

Saveをオンにした場合、処理完了後に一時Sceneから元Fileへ置き換えます。失敗時は元Fileを
保護します。ただし、Script自身が行うFile書き込みは制限されません。Maya Undoも使えないため、
**開発者向け / 要バックアップ**です。

## FBX を書き出す

### Export Selected FBX

Mesh、Skinned Mesh、Asset Group、Jointを選択してFBXへ書き出します。Skinned Meshを選んだ
場合は、必要な最上位Influence Jointも自動で含めます。

### Export Animation FBX

最上位のRoot Jointを1つ選択し、AnimationをBakeしてFBXへ書き出します。Time Sliderの
Highlightがあればその範囲、なければPlayback Rangeが使われます。

どちらも一時FBXへの書き出しが成功した場合だけ、出力先を置き換えます。失敗時は既存FBXを
保護し、Mayaの選択とFBX設定も復元します。ただし、成功した上書きは **ファイル保存**であり、
Maya Undoでは戻りません。

## ドキュメントを開く

`Documentation` は、設定された `DOCUMENTATION_ROOT` をブラウザで開きます。
シーンは変更しません。ローカルではこの [ツールガイド](README.md) を参照してください。

## 開発中のコードを再読み込みする

`Reload YWTA` は、読み込まれているYWTA Packageを再読み込みしてメニューを作り直します。
Sceneを直接編集する機能ではありませんが、既存UIや古いModule参照が残る可能性があります。
**開発者向け**として、Sceneを保存してから使用してください。
