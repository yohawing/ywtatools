# Geometry Nodes

Geometry Nodes EditorのAddメニューへ、2つの補助ノードを追加します。

## Reference

- **Menu:** Geometry Nodes Editorの `Add > Extra`
- **Undo:** BlenderのNode編集Undoに従います

## Group Wrapper

既存のGeometry Node Groupを選び、1つのNodeとして配置するためのwrapperです。
`Add > Extra > Group Wrapper`で追加し、Node上のselectorからNode Groupを指定します。

wrapperを複製すると、割り当てたNode Groupもcopyされます。

## Angle From Vector

2つのvectorからdegreeとradianを得るための試験的なcustom nodeです。

> [!WARNING]
> 現在の`Angle From Vector`には既知の実装不備があり、vector更新時に正しい出力を保証
> できません。本番作業では使用せず、Blender標準のVector Mathノードを使用してください。
