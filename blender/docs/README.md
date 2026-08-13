# YWTA Blender Manual

YWTA Blender Toolsの機能と使い方を、作業の種類ごとに説明します。インストールと
最初の操作については、[Blender README](../README.md)を参照してください。

## Sections

### [Modeling](modeling/README.md)

Hair TubeのCurve Cage化、Quad Remesh、ボリュームを保つSmoothingとBrush。

### [Shape Keys](shape-keys.md)

複数のShape Key名を検索し、まとめて置換します。

### [Geometry Nodes](geometry-nodes.md)

Geometry NodesのAddメニューへ補助ノードを追加します。

### [Interface](interface.md)

3D ViewportのYWTAタブと、Properties Editorに追加される補助パネルです。

## Conventions

メニュー名とボタン名はBlenderの表示に合わせています。各ページのReferenceには、
ツールの場所と実行前に選択するものを記載しています。

`Undo: Yes` は、オペレーターがBlenderのUndo対象として登録されていることを示します。
新しいObjectを作るツールもあるため、最初は保存済みファイルか複製データで試してください。

> [!NOTE]
> このマニュアルは現在の実装とテストを基にしています。すべてのページについて、今回
> Blender GUIでの手動操作をやり直したわけではありません。
