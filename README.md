# YWTA(YohaWing Technical Artist) Tools

個人プロジェクトでよく使うツールや、ツール開発するにあたっての便利なコンポーネントや関数を詰め込んだリポジトリです。

# Maya用ツール

[chadmv/cmt](https://github.com/chadmv/cmt)をベースにしています。

## インストール方法

`ywtatools.mod`をテキストファイルで開き`./`を解凍先のディレクトリに変更して、`ywtatools.mod`ファイルを`MAYA_MODULE_PATH`が通ったところにコピーしてください。


## How to build plugin

特定の機能を使う場合は、プラグインのビルドが必要です。プラグインのビルドにはVisual Studioとcmakeが必要です。
`maya/cpp/build.bat`を実行すると、自動的にpluginがビルドされ、所定のフォルダにプラグインがビルドされます。

## Dependency

Pythonの依存モジュールはRequirements.txtに記載しています。Mayapyへのインストールは自己責任でおねがいします。
```
C:\Program Files\Autodesk\Maya2024\bin\mayapy.exe -m pip install -r requirements.txt
```
# Blender用ツール
Blender用のツールは、Blenderのアドオンとして実装されています。
## インストール方法
Blenderのアドオンとしてインストールするには、Preferences > File Paths > Scripts Directoriesに、`path/to/ywtatools/blender`を追加してください。


# テストの実行方法

YWTAツールには、Maya環境とBlender環境の両方でテストを実行するための包括的なテストフレームワークが含まれています。

## Maya用テストの実行

### コマンドラインから実行

以下のコマンドを実行して、Maya 2024でテストを実行します。

```bash
python tests/run_maya_tests.py --pattern "test_*.py" --maya 2024

```

### Maya内から実行

Maya内でテストを実行するには、YWTA > Utility > Unit Test Runnerからテスト実行用のUIを開いてください。
