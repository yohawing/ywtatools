# YWTA Maya Tools

[← YWTA Tools のトップへ戻る](../README.md)

Maya 2024 でよく行うリギング、スキニング、アニメーション、メッシュ編集をまとめた
ツールセットです。インストールすると、Maya のメインメニューに `YWTA` が追加されます。

## ツールカタログ

メニュー項目ごとの前提条件、最小手順、成功確認、Undo/ロールバック、既知の制限は
[Maya ツールカタログ](docs/README.md) にまとめています。目的別に直接読む場合は、
[Rigging](docs/rigging/README.md)、[Deform](docs/deform/README.md)、
[Animation](docs/animation/README.md)、[Mesh](docs/mesh/README.md)、
[Pipeline / Export](docs/pipeline/README.md)、[Utility](docs/utility/README.md)
を選んでください。この README は導入・初回利用と開発者向け配置を扱い、機能の詳細は
カタログを正本とします。

## インストール

1. このリポジトリを任意の場所へ配置します。
2. ルートにある `ywtatools.mod` をテキストエディタで開きます。
3. ファイル内の `.\maya` を、配置した `maya` フォルダーの絶対パスへ書き換えます。
4. `ywtatools.mod` を `%USERPROFILE%\Documents\maya\modules` へコピーします。
5. Maya を起動し、メインメニューに `YWTA` が表示されれば完了です。

すでに別の `MAYA_MODULE_PATH` を使っている場合は、その中の modules フォルダーへ
コピーしても構いません。

一部の機能では `numpy`、`scipy`、`pyparsing` を使います。必要な場合は、リポジトリの
ルートで次のコマンドを実行してください。

```powershell
& "C:\Program Files\Autodesk\Maya2024\bin\mayapy.exe" -m pip install -r requirements.txt
```

## まず試す

インストールを確認するには、簡単なシーンを作り、`YWTA` メニューを開いてみてください。
たとえば次の操作は追加のビルドなしで試せます。

- ジョイントを選び、`YWTA > Rigging > Joint Edit Tools` を開く
- メッシュを選び、`YWTA > Utility > Scene Audit` でシーンを確認する
- オブジェクトを選び、`YWTA > Export Selected FBX` から書き出す

編集系のツールは、処理を始める前に対象を検証し、可能な限り一度の Undo で元へ戻せる
ように作っています。まずは複製したシーンで操作を確認してください。

## こんな作業に使えます

### ジョイントとコントロールを作る

`YWTA > Rigging` には、ジョイントの作成・挿入・方向調整・ミラー、階層リネーム、
Constraint、Swing/Twist、コントロールカーブの作成と編集をまとめています。Skeleton の
保存と読み込みや、HumanIK の自動セットアップもここから使います。

### スキンウェイトを直す

`YWTA > Deform` では、Skin Weight の保存・読み込み・転送、頂点ウェイトのコピーや
平均化、ミラー、スムージングができます。Skinned Mesh の結合・分離・複製、不要な
Influence の削除、Deformer の BlendShape 化も用意しています。

### Pose やアニメーションを使い回す

`YWTA > Animation` から、Pose と Animation Clip を保存・読み込みできます。Clip は
Replace / Place / Insert を選べるほか、選択中の対象だけへ適用できます。作業途中の
受け渡しには一時クリップボードも使えます。

### メッシュを整える

`YWTA > Mesh` には、頂点のロック、Skinning を保ったオブジェクト結合、クアッドへの
リメッシュ、Hair Tube Curve Cage、ボリュームを保つスムージングとブラシがあります。

Hair Tubeは初回に`uvx nox -s mesh_core_tests`、AutoRemesherとボリューム保持
スムージングは各ネイティブcomponentのビルドが必要です。Hair Tubeの最短手順は
[Hair Tube Curve Cage](docs/mesh/hair-tube.md)、ほかは
[C++ Components](cpp/README.md) と [Rust Components](../rust/README.md) を参照してください。

### シーンを確認して書き出す

トップレベルの `YWTA` メニューと `YWTA > Utility` には、Python スクリプト実行、
Batch Runner、FBX 書き出し、Scene Audit、Dependency Visualizer、Resource Browser
などがあります。

各機能の操作条件は [Maya ツールカタログ](docs/README.md) を参照してください。新しい
ツール群を追加した経緯、検証記録、計画資料は、Git管理外のローカル資料である
リポジトリルートの `docs/` に保存します。

## C++ プラグインを使う場合

Visual Studio 2022、CMake、Maya 2024 Developer Kit を用意し、リポジトリのルートで
次を実行します。

```powershell
maya\cpp\build.bat
```

AutoRemesher も含める場合は、先に外部コードを取得してください。

```powershell
git submodule update --init external/autoremesher
maya\cpp\build.bat
```

収録している C++ ノードとコマンドは [`maya/cpp/README.md`](./cpp/README.md) で確認できます。

## テスト

通常はリポジトリのルートから Nox 経由で実行します。

```powershell
uvx nox -s maya_tests -- --type unit --maya 2024
uvx nox -s maya_tests -- --type integration --maya 2024
```

Maya の中から確認したい場合は、`YWTA > Utility > Unit Test Runner` を開いてください。
その他の実行方法は [`tests/README.md`](../tests/README.md) にまとめています。

## 開発者向けの配置案内

```text
maya/ywta/       Python ツール本体
maya/ywta/menu/  YWTA メニュー
maya/cpp/        C++ プラグイン
maya/icons/      UI アイコン
maya/plug-ins/   ビルド済みプラグインの配置先
```
