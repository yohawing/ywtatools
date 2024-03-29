# YWTA(YohaWing Technical Artist) Tools

個人プロジェクトでよく使うツールや、ツール開発するにあたっての便利なコンポーネントや関数を詰め込んだリポジトリです。

[chadmv/cmt](https://github.com/chadmv/cmt)をベースにしています。

# Maya Module Install

以下のいずれかの方法でインストールしてください。
- 環境変数`MAYA_MODULE_PATH`のパスが通った場所（通常`Documents\maya\modules`）にこのリポジトリを置いてください。
- `Maya.env`の`MAYA_MODULE_PATH`にこのリポジトリのルートディレクトリを追加してください。
- *[推奨]*`ywtatools.mod`の`./`を解凍先のディレクトリに変更して、`cmt.mod`ファイルを`MAYA_MODULE_PATH`が通ったところにコピーしてください。


# How to build plugin

特定の機能を使う場合は、プラグインのビルドが必要です。プラグインのビルドにはVisual Studioとcmakeが必要です。
`maya/cpp/build.bat`を実行すると、自動的にpluginがビルドされ、所定のフォルダにプラグインがビルドされます。


# Dependency


Pythonの依存モジュールはRequirements.txtに記載しています。Mayapyへのインストールは自己責任でおねがいします。
```
C:\Program Files\Autodesk\Maya2022\bin\mayapy.exe -m pip install -r requirements.txt
```