"""RBF Mesh Retarget の最小ワークベンチ UI。

source / modified body と複数の follower を指定し、transaction 済みの
``meshretarget.retarget`` を呼び出します。Preview は低密度で実行し、作成した
duplicate は本適用やウィンドウ終了の前に追跡して削除します。
"""

from __future__ import absolute_import

try:
    # Maya 2024 の Qt binding を優先し、PySide6 環境でも同じ UI を利用する。
    from PySide2.QtWidgets import (
        QAbstractItemView,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        QWidget,
        QMainWindow,
    )
except ImportError:
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        QWidget,
        QMainWindow,
    )

import maya.cmds as cmds
from maya.app.general.mayaMixin import MayaQWidgetBaseMixin

from ywta.core.ui_utils import SingletonWindowMixin
from ywta.ui.widgets.mayanodewidget import MayaNodeWidget


# 4 は affine 項を含む RBF solver が最低限必要とする control point 数。
MIN_CONTROL_POINTS = 4
MAX_CONTROL_POINTS = 4096
PREVIEW_MAX_CONTROL_POINTS = 64
DEFAULT_MAX_CONTROL_POINTS = 256
meshretarget = None


def _backend():
    """RBF backendを遅延importする（numpy無しでもUIを開けるようにする）。"""
    global meshretarget
    if meshretarget is None:
        from ywta.rig import meshretarget as backend

        meshretarget = backend
    return meshretarget


def show():
    """RBF Mesh Retarget ウィンドウを表示する。"""
    MeshRetargetWindow.show_window()


def validate_max_control_points(value):
    """UIから受け取ったcontrol point数を安全な整数へ検証する。

    Args:
        value: 検証する値。

    Returns:
        範囲内の整数。

    Raises:
        ValueError: 整数でない、または安全な範囲外の場合。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("max control pointsは整数で指定してください")
    if not MIN_CONTROL_POINTS <= value <= MAX_CONTROL_POINTS:
        raise ValueError("max control pointsは{}〜{}の範囲で指定してください".format(MIN_CONTROL_POINTS, MAX_CONTROL_POINTS))
    return value


class MeshRetargetWindow(SingletonWindowMixin, MayaQWidgetBaseMixin, QMainWindow):
    """RBF Mesh Retarget を実行するワークベンチ。"""

    def __init__(self, parent=None):
        super(MeshRetargetWindow, self).__init__(parent)
        self.setWindowTitle("YWTA RBF Mesh Retarget")
        self.resize(460, 520)
        self.preview_duplicates = []
        self._preview_records = []

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.source_body = MayaNodeWidget("Source Body", "rbf_source_body", self)
        self.modified_body = MayaNodeWidget("Modified Body", "rbf_modified_body", self)
        layout.addWidget(self.source_body)
        layout.addWidget(self.modified_body)

        layout.addWidget(QLabel("Followers（複製して変形）", self))
        self.followers = QListWidget(self)
        self.followers.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.followers.setMinimumHeight(120)
        layout.addWidget(self.followers)

        follower_buttons = QHBoxLayout()
        add_button = QPushButton("Add Selected", self)
        add_button.setToolTip("現在選択しているmeshをfollowerへ追加します")
        add_button.clicked.connect(self.add_selected_followers)
        follower_buttons.addWidget(add_button)
        remove_button = QPushButton("Remove", self)
        remove_button.setToolTip("選択したfollowerを一覧から外します")
        remove_button.clicked.connect(self.remove_selected_followers)
        follower_buttons.addWidget(remove_button)
        clear_button = QPushButton("Clear", self)
        clear_button.setToolTip("follower一覧を空にします")
        clear_button.clicked.connect(self.clear_followers)
        follower_buttons.addWidget(clear_button)
        layout.addLayout(follower_buttons)

        control_points_layout = QHBoxLayout()
        control_points_layout.addWidget(QLabel("Apply max control points", self))
        self.max_control_points = QSpinBox(self)
        self.max_control_points.setRange(MIN_CONTROL_POINTS, MAX_CONTROL_POINTS)
        self.max_control_points.setValue(DEFAULT_MAX_CONTROL_POINTS)
        self.max_control_points.setToolTip(
            "本適用で使用するcontrol point数（{}〜{}）".format(MIN_CONTROL_POINTS, MAX_CONTROL_POINTS)
        )
        control_points_layout.addWidget(self.max_control_points)
        control_points_layout.addStretch(1)
        layout.addLayout(control_points_layout)

        action_buttons = QHBoxLayout()
        preview_button = QPushButton("Preview", self)
        preview_button.setToolTip("最大{}点の低密度でfollower duplicateを作成します".format(PREVIEW_MAX_CONTROL_POINTS))
        preview_button.clicked.connect(self.preview)
        action_buttons.addWidget(preview_button)
        apply_button = QPushButton("Apply", self)
        apply_button.setToolTip("指定したcontrol point数でfollowerを本適用します")
        apply_button.clicked.connect(self.apply)
        action_buttons.addWidget(apply_button)
        layout.addLayout(action_buttons)

    def _follower_names(self):
        """一覧に表示しているfollower名を返す。"""
        return [self.followers.item(index).text() for index in range(self.followers.count())]

    def add_selected_followers(self):
        """現在選択中のnodeを重複なしでfollower一覧へ追加する。"""
        existing = set(self._follower_names())
        for node in cmds.ls(sl=True, long=True) or []:
            if node not in existing:
                self.followers.addItem(QListWidgetItem(node))
                existing.add(node)

    def remove_selected_followers(self):
        """選択されたfollowerを一覧から削除する。"""
        for item in self.followers.selectedItems():
            row = self.followers.row(item)
            self.followers.takeItem(row)

    def clear_followers(self):
        """follower一覧を空にする。"""
        self.followers.clear()

    def _inputs(self):
        """UI上のsource / target / follower値を返す。"""
        return self.source_body.node, self.modified_body.node, self._follower_names()

    def _cleanup_preview(self):
        """追跡中のpreview duplicateを安全に削除する。"""
        records = list(self._preview_records)
        self._preview_records = []
        self.preview_duplicates = []
        for _duplicate, uuid in records:
            # UUIDから現在のlong pathを解決し、rename後も同じnodeだけを削除する。
            if not uuid:
                continue
            try:
                current = cmds.ls(uuid, long=True) or []
                if len(current) != 1:
                    continue
                cmds.delete(current[0])
            except Exception:
                # preview cleanupは本適用やcloseを妨げない。backendのUndo契約は維持する。
                continue

    def _track_preview(self, duplicates):
        """backendが返したduplicateをUUID付きで追跡する。"""
        self.preview_duplicates = list(duplicates or [])
        records = []
        for duplicate in self.preview_duplicates:
            try:
                uuids = cmds.ls(duplicate, uuid=True) or []
            except Exception:
                uuids = []
            if len(uuids) == 1:
                records.append((duplicate, str(uuids[0])))
        self._preview_records = records

    def _warn(self, error):
        """backendエラーを日本語警告として表示する。"""
        QMessageBox.warning(self, "RBF Mesh Retarget", "RBF retargetに失敗しました: {}".format(error))

    def preview(self):
        """低密度のpreview duplicateを作成する。"""
        self._cleanup_preview()
        try:
            source, target, followers = self._inputs()
            self._track_preview(
                _backend().retarget(
                    source,
                    target,
                    followers,
                    max_control_points=PREVIEW_MAX_CONTROL_POINTS,
                )
            )
        except Exception as error:
            self.preview_duplicates = []
            self._preview_records = []
            self._warn(error)

    def apply(self):
        """previewを削除し、UI指定のcontrol point数で本適用する。"""
        self._cleanup_preview()
        try:
            max_control_points = validate_max_control_points(self.max_control_points.value())
            source, target, followers = self._inputs()
            _backend().retarget(
                source,
                target,
                followers,
                max_control_points=max_control_points,
            )
        except Exception as error:
            self._warn(error)

    def closeEvent(self, event):
        """ウィンドウ終了時にpreview duplicateを削除する。"""
        self._cleanup_preview()
        super(MeshRetargetWindow, self).closeEvent(event)


__all__ = [
    "DEFAULT_MAX_CONTROL_POINTS",
    "MAX_CONTROL_POINTS",
    "MeshRetargetWindow",
    "MIN_CONTROL_POINTS",
    "PREVIEW_MAX_CONTROL_POINTS",
    "show",
    "validate_max_control_points",
]
