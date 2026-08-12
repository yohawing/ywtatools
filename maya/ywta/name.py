"""Maya ノード名を安全に一括編集するユーティリティ。"""

from __future__ import absolute_import

import re
import uuid

import maya.cmds as cmds


_TRAILING_NUMBER_PATTERN = r"^(.*?)(?:{separator})(\d+)$"


def _selected_nodes(nodes=None):
    """操作対象をロングパスで返す。"""
    result = cmds.ls(nodes, long=True) if nodes is not None else cmds.ls(selection=True, long=True)
    if not result:
        raise RuntimeError("名前を変更するノードを選択してください。")
    return result


def _split_leaf(node):
    """DAG パスから namespace とベース名を分離する。"""
    leaf = node.rsplit("|", 1)[-1]
    if ":" not in leaf:
        return "", leaf
    namespace, base = leaf.rsplit(":", 1)
    return namespace + ":", base


def _node_uuid(node):
    """ノードの UUID を取得する。"""
    values = cmds.ls(node, uuid=True) or []
    if len(values) != 1:
        raise RuntimeError("ノードを一意に解決できません: {}".format(node))
    return values[0]


def _resolve_uuid(node_uuid):
    """UUID から現在のロングパスを取得する。"""
    values = cmds.ls(node_uuid, long=True) or []
    if len(values) != 1:
        raise RuntimeError("名前変更中にノードを見失いました: {}".format(node_uuid))
    return values[0]


def _validate_leaf(name):
    """変更先の短いノード名を検証する。"""
    if not name:
        raise ValueError("変更後の名前が空です。")
    if "|" in name:
        raise ValueError("変更後の名前に DAG 区切り文字 '|' は使用できません: {}".format(name))


def _parent_identity(node):
    """同一親判定用の安定した識別子を返す。"""
    parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
    return _node_uuid(parents[0]) if parents else None


def rename_nodes(nodes, names):
    """複数ノードを一括 Undo 可能なトランザクションで変更する。

    親子を同時に変更してもパスが壊れないよう UUID で追跡し、一時名を
    経由することで選択内の名前交換にも対応する。Maya が名前を自動で
    uniquify した場合は失敗として一括で元に戻す。

    Args:
        nodes: 変更対象ノード。
        names: 対応する変更後の短い名前。

    Returns:
        変更後のロングパス一覧。
    """
    long_nodes = _selected_nodes(nodes)
    names = list(names)
    if len(long_nodes) != len(names):
        raise ValueError("ノード数と変更後の名前数が一致しません。")

    records = []
    targets = set()
    for node, name in zip(long_nodes, names):
        _validate_leaf(name)
        parent_id = _parent_identity(node)
        target = (parent_id, name)
        if target in targets:
            raise ValueError("同じ階層に重複する変更後の名前があります: {}".format(name))
        targets.add(target)
        records.append(
            {
                "uuid": _node_uuid(node),
                "name": name,
                "namespace": _split_leaf(node)[0],
            }
        )

    cmds.undoInfo(openChunk=True, chunkName="YWTA Name Tools")
    failed = False
    try:
        for record in records:
            node = _resolve_uuid(record["uuid"])
            temporary = "{}__ywta_rename_{}".format(record["namespace"], uuid.uuid4().hex)
            cmds.rename(node, temporary, ignoreShape=True)

        for record in records:
            node = _resolve_uuid(record["uuid"])
            renamed = cmds.rename(node, record["name"], ignoreShape=True)
            if renamed.rsplit("|", 1)[-1] != record["name"]:
                raise RuntimeError("名前が競合しています: {} -> {}".format(record["name"], renamed))
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()

    result = [_resolve_uuid(record["uuid"]) for record in records]
    cmds.select(result, replace=True)
    return result


def hash_rename(pattern, nodes=None, start=1):
    """``#`` の連続をゼロ埋め番号へ置換して選択順に変更する。"""
    if not pattern:
        raise ValueError("名前パターンが空です。")
    match = re.search(r"#+", pattern)
    if not match:
        raise ValueError("名前パターンには # を1つ以上含めてください。")
    selected = _selected_nodes(nodes)
    width = len(match.group(0))
    names = []
    for index, node in enumerate(selected, start=start):
        namespace, _ = _split_leaf(node)
        name = pattern[: match.start()] + str(index).zfill(width) + pattern[match.end() :]
        names.append(name if ":" in name else namespace + name)
    return rename_nodes(selected, names)


def find_replace(search, replacement="", nodes=None, case_sensitive=True):
    """選択ノードのベース名を検索置換する。"""
    if not search:
        raise ValueError("検索文字列が空です。")
    selected = _selected_nodes(nodes)
    names = []
    for node in selected:
        namespace, base = _split_leaf(node)
        if case_sensitive:
            changed = base.replace(search, replacement)
        else:
            changed = re.sub(re.escape(search), lambda _match: replacement, base, flags=re.IGNORECASE)
        names.append(namespace + changed)
    return rename_nodes(selected, names)


def add_affixes(prefix="", suffix="", nodes=None):
    """選択ノードのベース名へ prefix / suffix を追加する。"""
    if not prefix and not suffix:
        raise ValueError("prefix または suffix を指定してください。")
    selected = _selected_nodes(nodes)
    names = []
    for node in selected:
        namespace, base = _split_leaf(node)
        names.append(namespace + prefix + base + suffix)
    return rename_nodes(selected, names)


def remove_affixes(prefix="", suffix="", nodes=None):
    """一致する prefix / suffix を選択ノードから除去する。"""
    if not prefix and not suffix:
        raise ValueError("prefix または suffix を指定してください。")
    selected = _selected_nodes(nodes)
    names = []
    for node in selected:
        namespace, base = _split_leaf(node)
        if prefix and base.startswith(prefix):
            base = base[len(prefix) :]
        if suffix and base.endswith(suffix):
            base = base[: -len(suffix)]
        names.append(namespace + base)
    return rename_nodes(selected, names)


def renumber(nodes=None, separator="_", padding=2, start=1):
    """末尾の区切り文字と番号を除去し、選択順に振り直す。"""
    if padding < 1:
        raise ValueError("桁数は1以上にしてください。")
    selected = _selected_nodes(nodes)
    pattern = re.compile(_TRAILING_NUMBER_PATTERN.format(separator=re.escape(separator)))
    names = []
    for index, node in enumerate(selected, start=start):
        namespace, base = _split_leaf(node)
        match = pattern.match(base)
        stem = match.group(1) if match else base
        names.append(namespace + stem + separator + str(index).zfill(padding))
    return rename_nodes(selected, names)


def select_by_name(patterns):
    """空白区切りのワイルドカード群に一致するノードを選択する。"""
    patterns = patterns.split() if isinstance(patterns, str) else list(patterns)
    if not patterns:
        raise ValueError("検索パターンが空です。")
    nodes = []
    seen = set()
    for pattern in patterns:
        for node in cmds.ls(pattern, long=True) or []:
            node_id = _node_uuid(node)
            if node_id not in seen:
                seen.add(node_id)
                nodes.append(node)
    cmds.select(nodes, replace=True)
    return nodes


def show():
    """Name Tools ウィンドウを表示する。"""
    window = "ywtaNameToolsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="YWTA Name Tools", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, width=380)
    tabs = cmds.tabLayout(innerMarginWidth=8, innerMarginHeight=8)

    hash_tab = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    hash_field = cmds.textFieldGrp(label="Pattern", text="joint_##")
    cmds.button(
        label="Rename",
        command=lambda *_: hash_rename(cmds.textFieldGrp(hash_field, query=True, text=True)),
    )
    cmds.setParent("..")

    replace_tab = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    find_field = cmds.textFieldGrp(label="Find")
    replace_field = cmds.textFieldGrp(label="Replace")
    cmds.button(
        label="Replace",
        command=lambda *_: find_replace(
            cmds.textFieldGrp(find_field, query=True, text=True),
            cmds.textFieldGrp(replace_field, query=True, text=True),
        ),
    )
    cmds.setParent("..")

    affix_tab = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    prefix_field = cmds.textFieldGrp(label="Prefix")
    suffix_field = cmds.textFieldGrp(label="Suffix")
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1)
    cmds.button(
        label="Add",
        command=lambda *_: add_affixes(
            cmds.textFieldGrp(prefix_field, query=True, text=True),
            cmds.textFieldGrp(suffix_field, query=True, text=True),
        ),
    )
    cmds.button(
        label="Remove",
        command=lambda *_: remove_affixes(
            cmds.textFieldGrp(prefix_field, query=True, text=True),
            cmds.textFieldGrp(suffix_field, query=True, text=True),
        ),
    )
    cmds.setParent("..")
    cmds.setParent("..")

    renumber_tab = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    separator_field = cmds.textFieldGrp(label="Separator", text="_")
    padding_field = cmds.intFieldGrp(label="Padding", value1=2, minValue=1)
    cmds.button(
        label="Renumber",
        command=lambda *_: renumber(
            separator=cmds.textFieldGrp(separator_field, query=True, text=True),
            padding=cmds.intFieldGrp(padding_field, query=True, value1=True),
        ),
    )
    cmds.setParent("..")

    select_tab = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    select_field = cmds.textFieldGrp(label="Patterns", text="*_jnt")
    cmds.button(
        label="Select",
        command=lambda *_: select_by_name(cmds.textFieldGrp(select_field, query=True, text=True)),
    )
    cmds.setParent("..")

    cmds.tabLayout(
        tabs,
        edit=True,
        tabLabel=(
            (hash_tab, "Sequential"),
            (replace_tab, "Find / Replace"),
            (affix_tab, "Prefix / Suffix"),
            (renumber_tab, "Renumber"),
            (select_tab, "Select by Name"),
        ),
    )
    cmds.showWindow(window)
    return window


def rename_chain_ui():
    """旧 Rename Chain メニュー向けの互換エントリポイント。"""
    return show()
