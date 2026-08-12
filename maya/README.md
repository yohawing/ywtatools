# YWTA Maya Tools

[リポジトリ全体のインデックスへ戻る](../README.md)

Maya 2024 向けのリギング、デフォーメーション、アニメーション、メッシュ、入出力、
パイプライン支援ツールです。Python ツールと、処理負荷の高い機能を担う C++
プラグインを `YWTA` メニューから利用できます。

## インストール

1. リポジトリを任意の場所へ配置する
2. ルートの `ywtatools.mod` をテキストエディタで開く
3. 各 `ywtatools 1.0 .\maya` の `.\maya` を、配置先の `maya` ディレクトリへの絶対パスに変更する
4. `ywtatools.mod` を `MAYA_MODULE_PATH` が通る modules ディレクトリへコピーする
5. Maya を再起動し、メインメニューに `YWTA` が表示されることを確認する

ユーザー単位の標準的な modules ディレクトリは
`%USERPROFILE%\Documents\maya\modules` です。

一部の Python 機能は `numpy`、`scipy`、`pyparsing` を使用します。必要な場合は Maya
2024 の Python へ依存を導入してください。

```powershell
& "C:\Program Files\Autodesk\Maya2024\bin\mayapy.exe" -m pip install -r requirements.txt
```

## 主な機能

機能は Maya の `YWTA` メニューからカテゴリ別に開けます。

### Rigging

- Joint Edit Tools、階層のミラー、ジョイント挿入・方向調整・複製
- Name Tools、階層リネーム、ジョイント表示サイズ調整
- Constraint の作成・削除、Swing/Twist 接続
- Skeleton の JSON 入出力と一時クリップボード
- Control Creator、コントロールカーブの入出力・編集・結合
- 選択ナビゲーション、HumanIK Auto Setup

### Deform

- Skin Weight の保存、同一トポロジ読み込み、転送
- 頂点ウェイトのコピー、平均化、ミラー、スムージング
- Influence の追加・不要 Influence の削除
- Skinned Mesh の結合・分離・複製
- Shape 転送、Deformer の BlendShape 化、BlendShape Target Renamer

### Animation

- Selection Sets
- Pose の保存・読み込みと一時クリップボード
- Animation Clip の保存、Replace / Place / Insert 読み込み
- 選択対象への Clip 適用

### Mesh

- 頂点のロック・アンロック
- オブジェクトと Skinning の結合
- AutoRemesher Node による別オブジェクトへの非破壊クアッドリメッシュ
- Volume Preserving Smoothing と Volume Smooth Brush

AutoRemesher とボリューム保持スムージングは、利用前にネイティブコンポーネントの
ビルドが必要です。詳細は [C++ Components](../cpp/README.md) と
[Rust Components](../rust/README.md) を参照してください。

### Pipeline / Utility

- Python スクリプト実行と Batch Runner
- 選択オブジェクト／アニメーションの FBX Export
- Scene Audit、Dependency Visualizer、Resource Browser
- Maya 内 Unit Test Runner とモジュールの再読み込み

Fabricator を参考に追加した機能の採用範囲と設計は
[`docs/fabricator-maya-adoption.md`](../docs/fabricator-maya-adoption.md) を参照してください。

## C++ プラグインのビルド

Visual Studio 2022、CMake、Maya 2024 Developer Kit が必要です。

```powershell
maya\cpp\build.bat
```

ビルド対象のノードとコマンドについては [`cpp/README.md`](./cpp/README.md) を参照して
ください。AutoRemesher を含める場合は、先に submodule を取得します。

```powershell
git submodule update --init external/autoremesher
maya\cpp\build.bat
```

## テスト

```powershell
uvx nox -s maya_tests -- --type unit --maya 2024
uvx nox -s maya_tests -- --type integration --maya 2024
```

直接実行する場合は次の形式です。

```powershell
python tests/run_maya_tests.py --pattern "test_*.py" --maya 2024
```

Maya 内では `YWTA > Utility > Unit Test Runner` から実行できます。テスト種別や環境の
詳細は [`tests/README.md`](../tests/README.md) を参照してください。

## 実装場所

```text
maya/ywta/          Python モジュール
maya/ywta/menu/     YWTA メニュー登録
maya/cpp/           C++ プラグイン
maya/icons/         メニュー・UI アイコン
maya/plug-ins/      Maya バージョン別バイナリ配置先
```
