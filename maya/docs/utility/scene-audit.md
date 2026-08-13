# Scene Audit

Scene内の名前とMesh Topologyの問題を、修正せずに検査します。

## Reference

- **Menu:** `YWTA > Utility > Scene Audit`
- **Selection:** Scene全体を検査する場合は不要。部分検査ではMeshを選択

## Checks

- TransformまたはJointの重複したShort Name
- Non-manifold Vertex / Edge
- Lamina Face
- World Spaceで面積0または非有限のFace

## Usage

`Audit Scene`または`Audit Selected`を実行します。結果の項目を選び、`Select Issues`を使うと
該当NodeまたはComponentが選択されます。

Scene AuditはGeometryを変更せず、自動修復も行いません。
