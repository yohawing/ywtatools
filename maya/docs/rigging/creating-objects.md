# Creating Objects

選択範囲の中心へ基本Objectを作成します。

## Reference

- **Menu:** `YWTA > Rigging > Create at Selection Center`
- **Selection:** 配置基準にするObjectまたはComponent。選択なしでも実行可能
- **Undo:** 1回

## Usage

配置の基準にする要素を選択し、次のいずれかを実行します。

- `Null`
- `Locator`
- `Poly Cube`
- `Poly Sphere`
- `Poly Cylinder`
- `Poly Plane`

Objectは選択全体のWorld Bounding Boxの中心へ作成されます。選択がない場合は原点へ
作成されます。
