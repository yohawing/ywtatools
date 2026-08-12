# YWTA Rust Components

[リポジトリ全体のインデックスへ戻る](../README.md)

Maya と Blender で共有する DCC 非依存の処理を Rust crate として管理します。利用者向けの
操作方法は [Maya Tools](../maya/README.md) または
[Blender Tools](../blender/README.md) を参照してください。

## Mesh Smoothing

`rust/ywta-mesh-smoothing/` は、体積保持メッシュスムージングのソルバーです。通常の
スムージング、体積保持、凹凸除去、連続マスク、輪郭 rail を共通コアで処理し、C ABI
経由で各 DCC から呼び出します。

必要な環境は Windows 11 と Rust toolchain（Cargo）です。

```powershell
uvx nox -s mesh_smoothing_build
uvx nox -s mesh_smoothing_ffi_smoke
```

生成物は `bin/windows/ywta_mesh_smoothing.dll` です。Maya / Blender binding はこの場所を
既定値とし、`YWTA_MESH_SMOOTHING_DLL` で上書きできます。

## ディレクトリ

```text
rust/ywta-mesh-smoothing/src/lib.rs                    ソルバーと C ABI 実装
rust/ywta-mesh-smoothing/include/ywta_mesh_smoothing.h 公開 C ヘッダー
tests/native/test_ywta_mesh_smoothing_ffi.py           ctypes smoke test
```
