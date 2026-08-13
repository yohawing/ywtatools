# Constraints

複数のDriverから、最後に選択したDriven ObjectへConstraintを作成します。

## Reference

- **Menu:** `YWTA > Rigging > Constraints`
- **Selection:** Driverを先、Drivenを最後に選択
- **Undo:** 1回

## Usage

`Create Constraint...`を開くと、Constraint Type、Maintain Offset、Aim Axis、Up Axisを
設定できます。

次のメニューは、Maintain Offsetを有効にした既定値ですぐに作成します。

- `Parent Constraint`
- `Point Constraint`
- `Orient Constraint`
- `Scale Constraint`
- `Aim Constraint`

`Delete Constraints`は、選択したTransformを駆動しているConstraintを削除します。

## Notes

参照Node、重複したDriver、LockまたはAnimation接続があるDriven Channelは変更しません。
Aim Constraintでは、Aim VectorとUp Vectorがゼロまたは平行の場合も処理を中止します。
