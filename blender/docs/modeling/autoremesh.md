# AutoRemesh

選択MeshをQuad主体のTopologyへ変換し、結果を別Objectとして作ります。

## Reference

- **Menu:** Object Modeの `Object > AutoRemesh`
- **Selection:** ActiveなMesh Objectを1つ
- **Undo:** Yes

## Usage

1. Object ModeでMeshを選択します。
2. `Object > AutoRemesh`を実行します。
3. 目標三角形数、適応度、モデルタイプなどを設定します。
4. 確定し、処理の完了を待ちます。

元Objectと同じTransform、Collectionを持つ`<元の名前>_remeshed`が作られ、結果が選択
されます。実行後は`F9`のRedoパネルから設定を変更できます。

## Main Settings

`目標三角形数`は出力Quad数ではなく、処理へ渡す目標三角形数です。`適応度`を上げると
形状変化へ追従し、`モデルタイプ`ではOrganicとHard Surfaceを切り替えます。

## Requirements

Visual Studio 2022、CMake、AutoRemesher submoduleを用意し、次を実行します。

```powershell
git submodule update --init external/autoremesher
uvx nox -s autoremesher_build
```

通常は`bin/windows/ywta_autoremesher.dll`を使用します。別のDLLを使う場合は、Blenderを
起動する前に`YWTA_AUTOREMESHER_DLL`へ絶対パスを設定します。ビルドの詳細は
[C++ Components](../../../cpp/README.md)を参照してください。

## Known Limitations

UV、Material、Vertex Group、Shape Keyは結果へ転送されません。元Objectは変更されませんが、
大きなMeshでは処理に時間がかかるため、最初は低い目標数で確認してください。
