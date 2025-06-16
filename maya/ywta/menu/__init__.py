"""
メニューモジュール

YWTAツールのメニュー定義を提供します。
各カテゴリのメニュー定義は個別のモジュールに分離されています。
"""

from . import menu_animation
from . import menu_mesh
from . import menu_rigging
from . import menu_deform
from . import menu_utility
from . import core

# コア機能をエクスポート
from .core import create_menu, delete_menu, documentation
