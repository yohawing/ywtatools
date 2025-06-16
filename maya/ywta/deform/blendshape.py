import os
from six import string_types
import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim

import ywta.shortcuts as shortcuts
import ywta.deform.np_mesh as np_mesh
import ywta.rig.common as common


def get_blendshape_node(geometry):
    """指定されたジオメトリの上流にある最初のブレンドシェイプノードを取得します。

    :param geometry: ジオメトリの名前
    :return: ブレンドシェイプノードの名前
    """
    geometry = shortcuts.get_shape(geometry)
    history = cmds.listHistory(geometry, il=2, pdo=False) or []
    blendshapes = [
        x
        for x in history
        if cmds.nodeType(x) == "blendShape"
        and cmds.blendShape(x, q=True, g=True)[0] == geometry
    ]
    if blendshapes:
        return blendshapes[0]
    else:
        return None


def get_or_create_blendshape_node(geometry):
    """指定されたジオメトリの上流にある最初のブレンドシェイプノードを取得します。
    存在しない場合は新しく作成します。

    :param geometry: ジオメトリの名前
    :return: ブレンドシェイプノードの名前
    """
    geometry = shortcuts.get_shape(geometry)
    blendshape = get_blendshape_node(geometry)
    if blendshape:
        return blendshape
    else:
        return cmds.blendShape(geometry, foc=True)[0]


def get_target_index(blendshape, target):
    indices = cmds.getAttr("{}.w".format(blendshape), mi=True) or []
    for i in indices:
        alias = cmds.aliasAttr("{}.w[{}]".format(blendshape, i), q=True)
        if alias == target:
            return i
    raise RuntimeError(
        "Target {} does not exist on blendShape {}".format(target, blendshape)
    )


def add_target(blendshape, target_mesh_name, new_target_name=None):
    # Check if target already exists
    try:
        index = get_target_index(blendshape, target_mesh_name)
    except RuntimeError:
        index = cmds.getAttr("{}.w".format(blendshape), mi=True)
        index = index[-1] + 1 if index else 0

    base_shape = cmds.blendShape(blendshape, q=True, g=True)[0]
    cmds.blendShape(
        blendshape, edit=True, target=(base_shape, index, target_mesh_name, 1.0)
    )

    if new_target_name:
        cmds.aliasAttr(new_target_name, "{}.w[{}]".format(blendshape, index))

    return index


def get_target_list(blendshape):
    indices = cmds.getAttr("{}.w".format(blendshape), mi=True) or []
    targets = [
        cmds.aliasAttr("{}.w[{}]".format(blendshape, i), q=True) for i in indices
    ]
    return targets


def get_target_index(blendshape, target):
    indices = cmds.getAttr("{}.w".format(blendshape), mi=True) or []
    for i in indices:
        alias = cmds.aliasAttr("{}.w[{}]".format(blendshape, i), q=True)
        if alias == target:
            return i
    raise RuntimeError(
        "Target {} does not exist on blendShape {}".format(target, blendshape)
    )


def set_target_weights(blendshape, target, weights):
    index = get_target_index(blendshape, target)
    for i, w in enumerate(weights):
        cmds.setAttr(
            "{}.inputTarget[0].inputTargetGroup[{}].targetWeights[{}]".format(
                blendshape, index, i
            ),
            w,
        )


def zero_weights(blendshape):
    """ブレンドシェイプターゲットのウェイトへのすべての接続を切断し、
    ウェイトをゼロにします。

    :param blendshape: ブレンドシェイプノードの名前
    :return: 接続の辞書 dict[target] = [connection, original_value]
    """
    connections = {}
    targets = get_target_list(blendshape)
    for t in targets:
        plug = "{}.{}".format(blendshape, t)
        # 現在の値を保存
        original_value = cmds.getAttr(plug)
        connection = cmds.listConnections(plug, plugs=True, d=False)
        if connection:
            connections[t] = [connection[0], original_value]
            cmds.disconnectAttr(connection[0], plug)
        else:
            # 接続がない場合でも元の値を保存
            connections[t] = [None, original_value]
        cmds.setAttr(plug, 0)
    return connections


def restore_weights(blendshape, connections):
    """zero_weightsで切断されたウェイト接続を復元します。

    :param blendshape: ブレンドシェイプの名前
    :param connections: zero_weightsから返された接続の辞書
    """
    for target, data in connections.items():
        plug = "{}.{}".format(blendshape, target)
        connection, original_value = data
        if connection:
            cmds.connectAttr(connection, plug)
        else:
            # 接続がない場合は値を直接設定
            cmds.setAttr(plug, original_value)


def transfer_shapes(source, destination, blendshape=None):
    """指定されたブレンドシェイプのシェイプを宛先メッシュに転送します。

    ブレンドシェイプが間接的に宛先メッシュを変形させることを前提としています。

    :param source: シェイプを転送元のメッシュ
    :param destination: シェイプを転送先のメッシュ
    :param blendshape: オプションのブレンドシェイプノード名。ブレンドシェイプが指定されない場合、
        ソースメッシュ上のブレンドシェイプが使用されます。
    :return: 新しいブレンドシェイプノードの名前
    """
    if blendshape is None:
        blendshape = get_blendshape_node(source)
        if blendshape is None:
            return None

    connections = zero_weights(blendshape)
    targets = get_target_list(blendshape)
    new_targets = []

    # 転送先メッシュのヒストリーを削除して新しいシェイプを受け入れる準備をする
    cmds.delete(destination, ch=True)

    try:
        # 各ターゲットについて処理
        for t in targets:
            # ソースのブレンドシェイプターゲットをアクティブ化
            cmds.setAttr("{}.{}".format(blendshape, t), 1)
            # 転送先メッシュを複製して形状を保存
            target_mesh = cmds.duplicate(destination, name=t)[0]
            new_targets.append(target_mesh)
            # ソースのブレンドシェイプターゲットを非アクティブ化
            cmds.setAttr("{}.{}".format(blendshape, t), 0)

        # 転送先メッシュに新しいブレンドシェイプを作成
        new_blendshape = cmds.blendShape(new_targets, destination, foc=True)[0]

        # ターゲットごとに元のブレンドシェイプから新しいブレンドシェイプへ接続を作成
        for i, t in enumerate(targets):
            try:
                # 新しいブレンドシェイプノードのターゲットを名前で確認
                if cmds.attributeQuery(t, node=new_blendshape, exists=True):
                    cmds.connectAttr(
                        "{}.{}".format(blendshape, t), "{}.{}".format(new_blendshape, t)
                    )
                else:
                    # 名前でターゲットが見つからない場合はインデックスを使用
                    cmds.connectAttr(
                        "{}.{}".format(blendshape, t),
                        "{}.w[{}]".format(new_blendshape, i),
                    )
            except RuntimeError as e:
                cmds.warning("Failed to connect target '{}': {}".format(t, str(e)))

        # 複製したターゲットメッシュを削除
        cmds.delete(new_targets)
    except Exception as e:
        # エラーが発生した場合、中間オブジェクトをクリーンアップ
        if new_targets:
            cmds.delete(new_targets)
        raise RuntimeError("Error transferring shapes: {}".format(str(e)))
    finally:
        # 元のブレンドシェイプの重みを復元
        restore_weights(blendshape, connections)

    return new_blendshape


def propagate_neutral_update(old_neutral, new_neutral, shapes):
    """ニュートラル更新のデルタをターゲットシェイプに伝播します

    :param old_neutral: 古いニュートラルメッシュ
    :param new_neutral: 新しいニュートラルメッシュ
    :param shapes: 更新するシェイプのリスト
    """
    _old = np_mesh.Mesh.from_maya_mesh(old_neutral)
    _new = np_mesh.Mesh.from_maya_mesh(new_neutral)
    delta = _new - _old
    for shape in shapes:
        _shape = np_mesh.Mesh.from_maya_mesh(shape)
        new_shape = _shape + delta
        new_shape.to_maya_mesh(shape)


def create_shapes_joint(blendshapes, parent, name="shapes"):
    """各ブレンドシェイプターゲットごとにウェイト属性を持つジョイントを作成します。

    これはブレンドシェイプアニメーションをスケルトンと一緒にエクスポートするために使用されます。

    :param blendshapes: ブレンドシェイプノードのリスト
    :param parent: 新しいジョイントの親となるジョイント
    :param name: 新しいジョイントの名前。デフォルトは "shapes"
    :return: 新しいジョイントの名前
    """
    joint = cmds.createNode("joint", name=name)
    common.snap_to(joint, parent)
    cmds.parent(joint, parent)
    cmds.makeIdentity(joint, t=True, r=True, s=True, apply=True)
    if isinstance(blendshapes, string_types):
        blendshapes = [blendshapes]

    for blendshape in blendshapes:
        targets = get_target_list(blendshape)
        for t in targets:
            attr = "{}.{}".format(joint, t)
            if not cmds.objExists(attr):
                cmds.addAttr(joint, ln=t, keyable=True)
            if not cmds.listConnections(attr, d=False):
                cmds.connectAttr("{}.{}".format(blendshape, t), attr)
    return joint


def get_targets_at_index(blend_name, index=0):
    """
    ターゲットを返します。
    :param blend_name: <str> ブレンドシェイプノードの名前
    :param index: <int> シェイプのインデックス
    :return: <tuple> インデックスにあるターゲットの文字列配列
    """
    blend_fn = shortcuts.get_mfnblendshapedeformer(blend_name)
    # base_obj = get_base_object(blend_name)[0]
    obj_array = OpenMaya.MObjectArray()
    base_obj = OpenMaya.MObject()
    blend_fn.getBaseObjects(base_obj)
    blend_fn.getTargets(base_obj[0], index, obj_array)
    return obj_array


def get_base_object(blend_name):
    """
    ブレンドシェイプノードのベースオブジェクトを返します。
    :param blend_name: <str> ブレンドシェイプノードの名前
    :return: <tuple> ベースオブジェクトの文字列配列
    """
    blend_fn = shortcuts.get_mfnblendshapedeformer(blend_name)
    obj_array = OpenMaya.MObjectArray()
    blend_fn.getBaseObjects(obj_array)
    return obj_array[0]


def find_replace_target_names(blendshape, find_text, replace_text, case_sensitive=True):
    """ブレンドシェイプターゲット名のテキストを検索して置換します。

    :param blendshape: ブレンドシェイプノードの名前
    :param find_text: ターゲット名で検索するテキスト
    :param replace_text: 置換するテキスト
    :param case_sensitive: 検索が大文字と小文字を区別するかどうか（デフォルト: True）
    :return: 名前変更されたターゲットの old_name: new_name ペアを持つ辞書
    """
    if not cmds.objExists(blendshape):
        raise RuntimeError("BlendShape node '{}' does not exist".format(blendshape))

    if cmds.nodeType(blendshape) != "blendShape":
        raise RuntimeError("'{}' is not a blendShape node".format(blendshape))

    targets = get_target_list(blendshape)
    renamed_targets = {}

    for target in targets:
        if target is None:
            continue

        # Perform find and replace
        if case_sensitive:
            if find_text in target:
                new_name = target.replace(find_text, replace_text)
            else:
                continue
        else:
            if find_text.lower() in target.lower():
                # Case insensitive replacement
                import re

                new_name = re.sub(
                    re.escape(find_text), replace_text, target, flags=re.IGNORECASE
                )
            else:
                continue

        # Skip if name doesn't change
        if new_name == target:
            continue

        # Get the target index
        try:
            index = get_target_index(blendshape, target)

            # Rename the target by creating a new alias
            cmds.aliasAttr(new_name, "{}.w[{}]".format(blendshape, index))
            renamed_targets[target] = new_name

        except RuntimeError as e:
            cmds.warning("Failed to rename target '{}': {}".format(target, str(e)))
            continue

    return renamed_targets


def find_replace_target_names_regex(blendshape, pattern, replacement):
    """正規表現を使用してブレンドシェイプターゲット名のテキストを検索して置換します。

    :param blendshape: ブレンドシェイプノードの名前
    :param pattern: 検索する正規表現パターン
    :param replacement: 置換テキスト（\\1、\\2などの正規表現グループを含めることができます）
    :return: 名前変更されたターゲットの old_name: new_name ペアを持つ辞書
    """
    import re

    if not cmds.objExists(blendshape):
        raise RuntimeError("BlendShape node '{}' does not exist".format(blendshape))

    if cmds.nodeType(blendshape) != "blendShape":
        raise RuntimeError("'{}' is not a blendShape node".format(blendshape))

    targets = get_target_list(blendshape)
    renamed_targets = {}

    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise RuntimeError("Invalid regular expression pattern: {}".format(str(e)))

    for target in targets:
        if target is None:
            continue

        # Apply regex substitution
        new_name = regex.sub(replacement, target)

        # Skip if name doesn't change
        if new_name == target:
            continue

        # Get the target index
        try:
            index = get_target_index(blendshape, target)

            # Rename the target by creating a new alias
            cmds.aliasAttr(new_name, "{}.w[{}]".format(blendshape, index))
            renamed_targets[target] = new_name

        except RuntimeError as e:
            cmds.warning("Failed to rename target '{}': {}".format(target, str(e)))
            continue

    return renamed_targets
