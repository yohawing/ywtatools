"""
Shortcuts Module

このモジュールは、後方互換性のために維持されています。
新しいコードでは、maya.ywta.core パッケージの特定のモジュールを直接インポートすることをお勧めします。
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

logger = logging.getLogger(__name__)

# Maya API関連のユーティリティ
from maya.ywta.core.maya_utils import (
    get_mobject,
    get_dag_path,
    get_mfnmesh,
    get_points,
    set_points,
    get_mfnblendshapedeformer,
    get_int_ptr,
    ptr_to_int,
)

# ノード操作関連のユーティリティ
from maya.ywta.core.node_utils import (
    get_shape,
    get_node_in_namespace_hierarchy,
)

# 名前空間関連のユーティリティ
from maya.ywta.core.namespace_utils import (
    get_namespace_from_name,
    remove_namespace_from_name,
)

# UI関連のユーティリティ
from maya.ywta.core.ui_utils import (
    BaseTreeNode,
    SingletonWindowMixin,
    get_icon_path,
)

# 設定関連のユーティリティ
from maya.ywta.core.settings_utils import (
    get_setting,
    set_setting,
    get_save_file_name,
    get_open_file_name,
    get_directory_name,
    _get_file_path,
)

# ジオメトリ関連のユーティリティ
from maya.ywta.core.geometry_utils import (
    distance,
    vector_to,
)

# 非推奨の警告
import warnings


def _deprecated_warning(original_func):
    """非推奨の関数に警告を表示するデコレータ"""

    def wrapper(*args, **kwargs):
        warnings.warn(
            f"Function {original_func.__name__} in shortcuts.py is deprecated. "
            f"Use the equivalent function from maya.ywta.core instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return original_func(*args, **kwargs)

    return wrapper


# すべての関数に非推奨警告を適用
# 注：実際の実装では、必要に応じて特定の関数のみに適用することもできます
for name, func in list(locals().items()):
    if callable(func) and not name.startswith("_"):
        locals()[name] = _deprecated_warning(func)
