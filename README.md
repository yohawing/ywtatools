# YWTA(YohaWing Technical Artist) Tools

個人プロジェクトでよく使うツールや、ツール開発するにあたっての便利なコンポーネントや関数を詰め込んだリポジトリです。

# Maya用ツール

[chadmv/cmt](https://github.com/chadmv/cmt)をベースにしています。

Name Tools、Skin/Skeleton IO、Pose/Animation Clip、Selection Sets、Scene Audit、
Batch Runner、FBX Exporter の利用方法と採用境界は
[Fabricator 機能を参考にした Maya ツール拡充](./docs/fabricator-maya-adoption.md)を参照してください。

## インストール方法

`ywtatools.mod`をテキストファイルで開き`./`を解凍先のディレクトリに変更して、`ywtatools.mod`ファイルを`MAYA_MODULE_PATH`が通ったところにコピーしてください。


## How to build plugin

特定の機能を使う場合は、プラグインのビルドが必要です。プラグインのビルドにはVisual Studioとcmakeが必要です。
`maya/cpp/build.bat`を実行すると、自動的にpluginがビルドされ、所定のフォルダにプラグインがビルドされます。

## AutoRemesher（自動クアッドリメッシュ）

[huxingyi/autoremesher](https://github.com/huxingyi/autoremesher)（MIT）を組み込んだ自動リトポロジー機能です。初回のみ submodule の取得とビルドが必要です（VS2022 + CMake、Qt は不要）:

```
git submodule update --init external/autoremesher
uvx nox -s autoremesher_build   # Blender用DLL (bin/windows/ywta_autoremesher.dll)
maya\cpp\build.bat              # Mayaプラグイン (autoRemesherNode を含む)
```

- **Maya**: メッシュを選択して YWTA > Mesh > AutoRemesher Node。`<元名>_remeshed` オブジェクトが生成され、ノードの targetCount / adaptivity / modelType を変更すると再リメッシュされます（元メッシュは非破壊）
- **Blender**: オブジェクトを選択して Object メニュー > AutoRemesh。実行後は左下のRedoパネル（F9）でパラメータを調整できます

## Preserve Volume Smoothing

Maya / Blenderで共有するRust製メッシュスムージングソルバーです。利用前に
[Rust toolchain（Cargo）](https://www.rust-lang.org/tools/install) と `uvx` を用意し、
Windows 11上でリリースDLLをビルドしてください。

```bash
uvx nox -s mesh_smoothing_build
uvx nox -s mesh_smoothing_ffi_smoke
```

DLLは `bin/windows/ywta_mesh_smoothing.dll` に生成されます。このファイルはgit管理外です。
別の場所へ配置する場合は、Maya / Blenderの起動前に
`YWTA_MESH_SMOOTHING_DLL`へDLLの絶対パスを設定してください。

- **Maya**: モジュールをインストールしてMayaを起動し、メッシュまたは頂点を選択して YWTA > Mesh > Volume Preserving Smoothing、ブラシ操作は YWTA > Mesh > Volume Smooth Brush を選びます
- **Blender**: アドオンを有効化し、Edit Modeの Vertex メニューから Volume Preserving Smooth を実行します。Volume Smooth Brush は3D Viewport左側のToolbar（Tキー）で選択し、Tool Settingsから Smooth / Volume / Remove Bumps、半径、強度を調整します

通常スムージングは連続マスクと輪郭railに対応します。

- **Maya**: Vertex Soft Selectionをそのまま強度として使用します。面選択では選択パネルの内側だけを処理し、hard edge、crease、エッジ選択をrailとして保持します
- **Blender**: オペレータのVertex Group欄を指定するとグループウェイトをマスクとして使用します。hard edge、seam、crease、Edge Selectモードの選択エッジをrailとして保持します
- rail chainの内部頂点は輪郭接線方向だけ移動し、端点、分岐、鋭いcornerは固定します

Blenderテストはインストール済みの最新版を自動検出します。検出できない場合は
`BLENDER_EXECUTABLE`へ `blender.exe` の絶対パスを設定してください。

```bash
uvx nox -s blender_tests
```

## Dependency

Pythonの依存モジュールはRequirements.txtに記載しています。Mayapyへのインストールは自己責任でおねがいします。
```
C:\Program Files\Autodesk\Maya2024\bin\mayapy.exe -m pip install -r requirements.txt
```
# Blender用ツール
Blender用のツールは、Blenderのアドオンとして実装されています。
## インストール方法
Blenderのアドオンとしてインストールするには、Preferences > File Paths > Scripts Directoriesに、`path/to/ywtatools/blender`を追加してください。

# Photoshop用ツール

Photoshop用のツールは UXP Manifest v5 プラグインとして実装します。
開発環境の準備と UXP Developer Tool からの読み込み方法は
[photoshop/README.md](./photoshop/README.md) を参照してください。


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

# 開発者向け情報

開発ルール・コーディング規約・コミット規律などは [AGENTS.md](./AGENTS.md) を参照してください。
Lintは以下のコマンドで実行できます。

```bash
ruff check .
```


Humanikの半自動マッピングを作ってみたい。
