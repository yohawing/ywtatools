# AutoRemesher

選択Meshを入力にしたNodeを作り、別のMeshへQuad主体のTopologyを出力します。

## Reference

- **Menu:** `YWTA > Mesh > AutoRemesher Node`
- **Selection:** Mesh TransformまたはMesh Shapeを1つ

## Usage

1. Meshを選択します。
2. AutoRemesher Nodeを開きます。
3. Target Count、Adaptivity、Model Typeなどを設定します。
4. `Create Node`を実行します。

元Mesh、`autoRemesherNode`、出力Meshが接続されます。Nodeの設定を変更すると出力が
再計算されます。

## Requirements

AutoRemesherを含むMaya C++ Pluginが必要です。ビルド方法は
[Maya README](../../README.md#c-プラグインを使う場合)を参照してください。

## Known Limitations

Node作成は一括Transactionを持たないため、Sceneのコピーで使用してください。UVとSkin Weightは
出力Meshへ転送されません。
