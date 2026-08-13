# YWTA Maya Manual

YWTA Maya Toolsは、リギング、スキニング、アニメーション、メッシュ編集、書き出しを
支援するMayaツールセットです。実行環境とC++プラグインの対象は
[Mayaバージョンサポート](maya-version-support.md)を参照してください。

このマニュアルは、ツールの目的と使い方を説明します。インストールについては
[Maya README](../README.md)を参照してください。

## Sections

### [Rigging](rigging/README.md)

Jointの作成と編集、Constraint、Skeletonの入出力、Control Curve、HumanIK。

### [Deform](deform/README.md)

Skin Weightの保存と編集、Influence、Skinned Mesh、BlendShape、Deformer。

### [Animation](animation/README.md)

Selection Set、Pose、Animation Clipの保存と再利用。

### [Mesh](mesh/README.md)

頂点ロック、階層からのMesh生成、AutoRemesher、Volume Preserving Smoothing。

### [Pipeline and Export](pipeline/README.md)

Python Scriptの実行、複数SceneのBatch処理、FBX Export。

### [Utility](utility/README.md)

Scene Audit、Test Runner、依存関係の確認、開発中のModule Reload。

## Conventions

メニュー名とボタン名は、Mayaの英語UIに合わせて記載しています。

各ページのReferenceには、ツールを開く場所と、実行前に選択するものを示します。
ファイルへ保存する操作はMayaのUndoでは戻りません。Undoについて特別な制限がある場合は、
各ページのNotesまたはKnown Limitationsに記載します。

> [!NOTE]
> このマニュアルは現在の実装とテストを基にしています。今回、すべてのツールをMaya GUIで
> 操作する実機確認は行っていません。
