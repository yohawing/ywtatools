# Maya バージョンサポートと C++ プラグインビルド

## 対応マトリクス

| Maya | 実行環境 | C++ ビルド対象 | Qt バインディング（実測） | Qt バージョン（実測） |
| --- | --- | --- | --- | --- |
| 2024 | Python 3.10.8 | 既存バイナリの互換性・テスト基準 | PySide2 | 5.15.2 |
| 2025 | Python 3.11.4 | Release ビルド対象 | PySide6 | 6.5.3 |
| 2026 | Python 3.11.9 | Release ビルド対象 | PySide6 | 6.5.3 |
| 2027 | Python 3.13.9 | Release ビルド対象 | PySide6 | 6.8.3 |

新しい C++ ビルドの対象は Maya 2025–2027 です。Maya 2024 の
`maya/plug-ins/2024/ywtatools.mll` は既存の互換性・テスト基準として保持し、ビルド
スクリプトから上書きしません。PySide の分岐が必要な Python/UI コードでは、上表の
実測結果に基づき PySide6（2025以降）と PySide2（2024）を選択してください。

## 前提条件

- Windows 11 x64
- Autodesk Maya 2025、2026、2027 の各 `include/maya` と `lib`（`Foundation.lib`
  を含む）が `C:\Program Files\Autodesk\Maya<version>` に存在すること
- Visual Studio 2022 C++ x64 ツールチェーン（実測 installationVersion 17.14.37314.3）
- Ninja（PATH から `ninja` として解決できること）
- CMake 4.2.1（`cmake --version` で確認）
- リポジトリの `external/autoremesher` submodule が初期化済みであること。submodule
  内のファイルは変更しません。

## ビルドコマンド

全対象を 2025 → 2026 → 2027 の順でビルドする場合:

```powershell
Set-Location maya/cpp
.\build.bat
```

対象を明示する場合（複数指定も指定順に逐次実行）:

```powershell
.\build.bat 2026
.\build.bat 2025 2027
```

リポジトリルートからは Nox の薄いラッパーを利用できます。

```powershell
uvx nox -s maya_plugin_build
uvx nox -s maya_plugin_build -- 2026
uvx nox -s maya_plugin_build -- 2025 2027
```

`build.bat` は `vswhere` で Visual Studio 2022（17.x）の C++ x64 toolchain を解決し、
`VsDevCmd.bat -arch=x64` で環境を初期化します。その後、
`cmake -S . -B build.<version>-ninja -G Ninja -DCMAKE_BUILD_TYPE=Release -DMAYA_VERSION=<version>` と
`cmake --build ... --target install --config Release` を実行します。ビルドディレクトリは再利用し、
無条件の再帰削除は行いません。Visual Studio 2022 のコンパイラーを Ninja から呼び出すため、
Visual Studio 18 が PATH の既定値になる環境でも Maya 対応ツールチェーンを固定します。
生成物は次の場所にインストールされます。

```
maya/plug-ins/2025/ywtatools.mll
maya/plug-ins/2026/ywtatools.mll
maya/plug-ins/2027/ywtatools.mll
```

## 検証ゲート

1. 各バージョンを前のプロセス終了後に順番に Configure → Release Build し、終了コード
   が 0 であることを確認する。1つでも失敗したら後続バージョンを実行しない。
2. 3つの `.mll` が存在し、サイズが 0 より大きいことを確認し、SHA-256 を記録する。
3. 各 Maya に対応する `mayapy.exe` を使い、バージョンごとに異なる一時
   `MAYA_APP_DIR` を設定してロード・アンロード smoke を逐次実行する。ロード後に
   `pluginInfo(..., loaded=True)` が真で、`autoRemesherNode` を作成できることを確認する。

例（PowerShell、`$version` ごとに1回ずつ実行）:

```powershell
$version = 2026
$env:MAYA_APP_DIR = Join-Path $env:TEMP "ywta-maya-smoke-$version"
$mayapy = "C:\Program Files\Autodesk\Maya$version\bin\mayapy.exe"
$plugin = (Resolve-Path "maya/plug-ins/$version/ywtatools.mll").Path
& $mayapy -c "import maya.standalone; maya.standalone.initialize(name='python'); import maya.cmds as cmds; p=r'$plugin'; cmds.loadPlugin(p); assert cmds.pluginInfo(p, query=True, loaded=True); n=cmds.createNode('autoRemesherNode'); print(n); cmds.unloadPlugin(p); maya.standalone.uninitialize()"
```

4. ビルド前に記録した Maya 2024 バイナリの SHA-256 と、検証後の値が一致することを
   確認する。既存基準の変更が必要な場合は別途承認を得る。

## 失敗時の再実行とロールバック

Configure または Build が失敗した場合、`build.<version>-ninja` のログを確認して原因を修正し、
同じコマンドを再実行します。ビルドスクリプトは既存ディレクトリを再利用するため、
手動で削除せず CMake を再 Configure してください。失敗したバージョン以降は実行されない
ので、修正後にそのバージョンから順番を保って再開します。

配布前に問題が見つかった場合は、SHA-256 と出所を確認済みの旧 `.mll` を対象バージョン
へ戻し、ロード smoke を再実行します。Maya 2024 の既存バイナリや
`external/autoremesher` submodule はこの手順で変更しません。
