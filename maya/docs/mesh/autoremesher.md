# AutoRemesher

選択Meshを入力にしたNodeを作り、別のMeshへQuad主体のTopologyを出力します。

## Reference

- **Menu:** `YWTA > Mesh > AutoRemesher Node` / `Finalize AutoRemesher...`
- **Selection:** Mesh TransformまたはMesh Shapeを1つ

## Usage

1. Meshを選択します。
2. AutoRemesher Nodeを開きます。
3. Target Count、Adaptivity、Model Typeなどを設定します。
4. `Create Node`を実行します。

元Mesh、`autoRemesherNode`、出力Meshが接続されます。Nodeの設定を変更すると出力が
再計算されます。

### 結果の確定

1. `autoRemesherNode`、またはその出力Meshを1つ選択します。
2. `Finalize AutoRemesher...`を実行します。

AutoRemesherの現在結果をtargetへbakeし、sourceのヒストリを保持したまま、sourceの
全UV setをclosest pointで転送します。sourceにskinClusterがある場合は、skin weightも
`closestPoint`で転送します。Undoは1回で確定処理全体を戻せます。転送に失敗した場合は
sceneとselectionを処理前へ戻します。

## Requirements

AutoRemesherを含むMaya C++ Pluginが必要です。ビルド方法は
[Maya README](../../README.md#c-プラグインを使う場合)を参照してください。

## Known Limitations

Node作成自体は一括Transactionを持たないため、作成前に必要ならSceneを保存してください。
FinalizeはUndo対応の単一chunkですが、sourceのskin influenceがlockedの場合は事前検証で
拒否します。copySkinWeights開始後の失敗はsceneとselectionを処理前へrollbackしますが、
Mayaがそれ以前のUndo queueを保持しない場合があります。
Skin転送のUndo責務はFinalizeの外側chunkが所有し、通常のSkin IO単独利用時は従来どおり
Skin IO自身がUndoを管理します。
