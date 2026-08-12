"""MFnSkinCluster bulk write に Undo/Redo を付与する Maya Python plugin。"""

from __future__ import absolute_import

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

from ywta.deform import skin_weight_command


def maya_useNewAPI():
    """Maya に Python API 2.0 plugin であることを通知する。"""


def _depend_node(name):
    """node 名から dependency MObject を取得する。"""
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDependNode(0)


def _dag_node(name):
    """DAG node 名から MObject を取得する。"""
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDagPath(0).node()


def _component(indices):
    """頂点 index 列から component object を作る。"""
    component = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
    om.MFnSingleIndexedComponent(component).addElements(indices)
    return component


class YwtaSetSkinWeightsCommand(om.MPxCommand):
    """新旧 dense weights を保持する undoable command。"""

    def __init__(self):
        super(YwtaSetSkinWeightsCommand, self).__init__()
        self._cluster = None
        self._shape = None
        self._component_indices = None
        self._influence_indices = None
        self._all_influence_indices = None
        self._new_weights = None
        self._old_weights = None
        self._normalize = True

    @staticmethod
    def creator():
        """Maya command creator。"""
        return YwtaSetSkinWeightsCommand()

    def doIt(self, args):
        """registry operation を受け取り初回 write を行う。"""
        if len(args) != 1:
            raise RuntimeError("operation token を1つ指定してください。")
        operation = skin_weight_command.take_operation(args.asString(0))
        self._cluster = om.MObjectHandle(_depend_node(operation["cluster"]))
        self._shape = om.MObjectHandle(_dag_node(operation["shape"]))
        self._component_indices = operation["component_indices"]
        self._new_weights = om.MDoubleArray(operation["weights"])
        self._normalize = operation["normalize"]
        fn_skin, _shape_path = self._objects()
        influence_count = len(fn_skin.influenceObjects())
        self._influence_indices = om.MIntArray(operation["influence_indices"])
        self._all_influence_indices = om.MIntArray(range(influence_count))
        self._set_new_weights(capture_old=True)

    def _objects(self):
        """保持中 handle から skin function と現在の DAG path を取得する。"""
        if not self._cluster.isValid() or not self._shape.isValid():
            raise RuntimeError("skinCluster または mesh shape が無効です。")
        fn_skin = oma.MFnSkinCluster(self._cluster.object())
        shape_path = om.MDagPath.getAPathTo(self._shape.object())
        return fn_skin, shape_path

    def _set_new_weights(self, capture_old=False):
        """new weights を設定し、初回だけ old weights を保存する。"""
        fn_skin, shape_path = self._objects()
        component = _component(self._component_indices)
        if capture_old:
            old_weights, _influence_count = fn_skin.getWeights(shape_path, component)
            self._old_weights = om.MDoubleArray(old_weights)
        fn_skin.setWeights(
            shape_path,
            component,
            self._influence_indices,
            self._new_weights,
            normalize=self._normalize,
            returnOldWeights=False,
        )

    def redoIt(self):
        """保存済み new weights を再適用する。"""
        self._set_new_weights(capture_old=False)

    def undoIt(self):
        """初回 write 前の weights を復元する。"""
        fn_skin, shape_path = self._objects()
        fn_skin.setWeights(
            shape_path,
            _component(self._component_indices),
            self._all_influence_indices,
            self._old_weights,
            normalize=False,
        )

    def isUndoable(self):
        """Maya Undo queue 対応を宣言する。"""
        return True


def initializePlugin(plugin_object):
    """command を Maya に登録する。"""
    plugin = om.MFnPlugin(plugin_object, "yohawing", "1.0.0", "Any")
    plugin.registerCommand(
        skin_weight_command.COMMAND_NAME,
        YwtaSetSkinWeightsCommand.creator,
    )


def uninitializePlugin(plugin_object):
    """command 登録を解除する。"""
    plugin = om.MFnPlugin(plugin_object)
    plugin.deregisterCommand(skin_weight_command.COMMAND_NAME)
