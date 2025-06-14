# YWTA Core モジュール

## 概要

`ywta.core`パッケージは、YWTAツールセット全体で使用される共通のユーティリティ関数とクラスを提供します。このパッケージは、以前は`shortcuts.py`に含まれていた機能を機能別に整理し、より明確な責任分担と依存関係を持つモジュール構造に再編成しています。

## モジュール構造

`core`パッケージは以下のモジュールで構成されています：

### 1. `maya_utils.py`

Maya APIを使用するための低レベルユーティリティ関数を提供します。

- `get_mobject()` - ノード名からMObjectを取得
- `get_dag_path()` - ノード名からMDagPathを取得
- `get_mfnmesh()` - メッシュのMFnMeshを取得
- `get_points()` - メッシュの頂点位置を取得
- `set_points()` - メッシュの頂点位置を設定
- `get_mfnblendshapedeformer()` - ブレンドシェイプのMFnBlendShapeDeformerを取得
- `get_int_ptr()`, `ptr_to_int()` - MScriptUtil関連のユーティリティ

### 2. `node_utils.py`

Mayaのノード操作に関連するユーティリティ関数を提供します。

- `get_shape()` - トランスフォームのシェイプノードを取得
- `get_node_in_namespace_hierarchy()` - 名前空間階層内のノードを検索

### 3. `namespace_utils.py`

名前空間操作に関連するユーティリティ関数を提供します。

- `get_namespace_from_name()` - 名前から名前空間を抽出
- `remove_namespace_from_name()` - 名前から名前空間を削除

### 4. `ui_utils.py`

ユーザーインターフェース関連のクラスと関数を提供します。

- `BaseTreeNode` - QAbstractItemModelで使用するための階層機能を持つ基本クラス
- `SingletonWindowMixin` - ウィンドウのインスタンスを1つだけ許可するミックスイン
- `get_icon_path()` - アイコンファイルのパスを取得

### 5. `settings_utils.py`

設定の保存と読み込みに関連するユーティリティ関数を提供します。

- `get_setting()`, `set_setting()` - 永続的な設定の取得と保存
- `get_save_file_name()`, `get_open_file_name()`, `get_directory_name()` - ファイルダイアログ関連の関数

### 6. `geometry_utils.py`

ジオメトリ操作と数学計算に関連するユーティリティ関数を提供します。

- `distance()` - 2つのノード間の距離を計算
- `vector_to()` - 2つのノード間のベクトルを計算
- `get_bounding_box()` - ノードのバウンディングボックスを取得
- `get_center_point()` - ノードの中心点を取得
- `create_vector()` - MVectorを作成
- `normalize_vector()` - ベクトルを正規化
- `dot_product()`, `cross_product()` - ベクトル演算

## 使用方法

### 推奨される使用方法

新しいコードでは、必要な機能を持つ特定のモジュールを直接インポートすることをお勧めします：

```python
# 例：Maya APIユーティリティを使用する場合
from ywta.core.maya_utils import get_mfnmesh, get_points

# 例：ジオメトリユーティリティを使用する場合
from ywta.core.geometry_utils import distance, vector_to
```

### 後方互換性

既存のコードとの互換性のために、`shortcuts.py`モジュールは引き続き使用できますが、非推奨とマークされています：

```python
# 非推奨の使用方法（警告が表示されます）
from ywta.shortcuts import get_shape, distance
```

## レイヤードアーキテクチャ

`core`パッケージは、以下のようなレイヤー構造を採用しています：

1. **基盤レイヤー**：Maya API関連のユーティリティ（`maya_utils.py`）
2. **中間レイヤー**：ノード操作、名前空間、ジオメトリなどの基本機能（`node_utils.py`, `namespace_utils.py`, `geometry_utils.py`）
3. **上位レイヤー**：UI、設定などのユーザー向け機能（`ui_utils.py`, `settings_utils.py`）

この構造により、依存関係が明確になり、各モジュールの責任範囲が明確になります。上位レイヤーのモジュールは下位レイヤーのモジュールに依存することがありますが、その逆は避けるべきです。
