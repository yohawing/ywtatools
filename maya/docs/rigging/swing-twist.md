# Swing/Twist

DriverのSwingとTwistを分解し、Driven Transformの`offsetParentMatrix`へ接続します。

## Reference

- **Menu:** `YWTA > Rigging > Connect Twist Joint`
- **Selection:** Driverを先、Drivenを最後に選択

## Usage

Option BoxでTwist Axis、Twist Weight、Swing Weightを設定し、`Connect Twist Joint`を
実行します。作成後、Driverを回転してDrivenが期待どおり追従することを確認します。

## Notes

Maya Pluginと複数のDG Nodeを作る従来処理です。既存接続を含めた一括Rollbackは保証されません。
保存済みSceneのコピーで使用してください。
