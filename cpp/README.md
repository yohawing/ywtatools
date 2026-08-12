# YWTA C++ Components

[リポジトリ全体のインデックスへ戻る](../README.md)

Maya と Blender から利用する共有 C++ コンポーネントです。利用者向けの操作方法は
[Maya Tools](../maya/README.md) または [Blender Tools](../blender/README.md) を参照して
ください。

## AutoRemesher Core

`cpp/autoremesher_core/` は
[huxingyi/autoremesher](https://github.com/huxingyi/autoremesher) の Qt 非依存コアを
ビルドし、Blender などから呼び出せる C ABI DLL を提供します。外部ソースは
`external/autoremesher` submodule の 1.0.0 に固定しており、submodule 内は変更しません。

必要な環境は Windows 11、Visual Studio 2022、CMake です。Qt は不要です。

```powershell
git submodule update --init external/autoremesher
uvx nox -s autoremesher_build
```

生成物は `bin/windows/ywta_autoremesher.dll` です。Blender の ctypes binding はこの場所を
既定値とし、`YWTA_AUTOREMESHER_DLL` で上書きできます。

Maya C++ プラグインは同じコアを静的リンクします。

```powershell
maya\cpp\build.bat
```

## ディレクトリ

```text
cpp/autoremesher_core/CMakeLists.txt  コアと C ABI DLL のビルド定義
cpp/autoremesher_core/capi.h          公開 C ABI
cpp/autoremesher_core/qtshim/         submodule を変更しないための互換ヘッダー
external/autoremesher/                固定された外部 submodule
```

Maya 固有の C++ ノードとコマンドは [`maya/cpp/README.md`](../maya/cpp/README.md) を参照して
ください。
