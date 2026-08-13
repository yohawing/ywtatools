# Vertex Lock

選択したPolygon VertexのLock属性を変更します。

## Reference

- **Menu:** `YWTA > Mesh > Lock Selected Vertices` / `Unlock Selected Vertices`
- **Selection:** Polygon Vertex

## Usage

Component Modeで頂点を選択し、LockまたはUnlockを実行します。Geometry自体は変わりません。

## Notes

一括Undoや失敗時のRollbackを持たない従来処理です。頂点を選択せずに実行するとエラーに
なる場合があります。少数の頂点で通常のMaya Undoを確認してから使用してください。
