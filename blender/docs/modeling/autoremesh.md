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
されます。元Objectは`YWTA AutoRemesh Sources` Collectionへ移動し、Viewport/Renderから
非表示になります。生成Objectを選んでもう一度`AutoRemesh`を実行すると、保持元から同じ
生成Objectを更新できます。前回設定がdialogへ復元されます。

元Objectを直接確認するときは、生成Objectを選んで`Object > Reveal AutoRemesh Source`を
実行します。保持Collectionを表示して元Objectを選択します。いずれの操作もUndoできます。

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

UV、Material、Vertex Group、Shape Keyは結果へ転送されません。元Objectのmeshデータは変更されませんが、
大きなMeshでは処理に時間がかかるため、最初は低い目標数で確認してください。
