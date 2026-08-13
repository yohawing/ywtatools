# Rigging

[← Manual](../README.md)

Joint、Constraint、Skeleton、Control Curveを扱うツールです。

- [Riggingツール棚卸しと整理決定](tool-inventory.md) — 現行配置、重複、UI/Undo要件、整理後のメニュー構成

## Joint

- [Joint Editing](joint-editing.md) — Joint Edit Tools、作成、挿入、Orient、Mirror、複製
- [Creating Objects](creating-objects.md) — 選択範囲の中心へNullやPrimitiveを作成
- [Naming and Selection](naming-selection.md) — 名前変更、関連JointやMeshの選択、Snap

## Rig Construction

- [Constraints](constraints.md) — Parent、Point、Orient、Scale、Aim Constraint
- [Skeleton I/O](skeleton-io.md) — SkeletonのJSON保存と読み込み
- [Control Curves](control-curves.md) — Controlの作成、保存、交換、Mirror、結合
- [Swing/Twist](swing-twist.md) — Twist Joint接続
- [HumanIK Auto Setup](humanik.md) — 限定的なHumanIK Character作成
- [HumanIK Auto Assignment 出力境界](humanik-auto-assignment-boundary.md) — `yw-retarget`との未実装の受け渡し仕様
- [HumanIK donor 移植境界](humanik-donor-boundary.md) — donorから採用する安全性と移植しないMMD固有責務
- [RBF Mesh Retarget](mesh-retarget.md) — 対応ボディ間の変形を衣装などへ転送（Workbench UIを含む）
