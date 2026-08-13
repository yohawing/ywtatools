# Control Curves

NURBS Curve Controlの作成、保存、Shape交換、Mirror、結合を行います。

## Reference

- **Menu:** `YWTA > Rigging`
- **Selection:** 操作対象のCurve Transform
- **Undo:** Shapeの作成と編集は1回。Library Fileの変更はMaya Undoの対象外

## Control Creator

`Control Creator`は、Curveの作成とLibrary管理をまとめたウィンドウです。Shapeを選び、
原点または選択範囲の中心へControlを作成できます。色、CV、Mirror、Combineも編集できます。

Libraryの保存、改名、削除はFile操作です。既存Libraryを残したい場合は、先にBackupを
作成してください。

## Curve Tools

**Export Selected Control Curves** — 選択したCurveをJSONへ保存します。

**Import Control Curves** — JSONに保存された名前で新しいControlを作成します。

**Swap Selected Control Shapes** — Transform、Key、Constraintを残し、Shapeだけを交換します。

**Mirror Selected Control Shape** — 反対側のControlへ、World YZ面で反転したShapeを設定します。

**Edit Selected Control CVs** — 選択したControl直下のCurve CVをComponent選択します。

**Combine Selected Control Shapes** — 最後に選択したControlへShapeを集約し、ほかの
Source Transformを削除します。
