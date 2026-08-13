"""ヒューマンIK関連のモジュールと便利スクリプト

Functions:
- モーションデータのインポートと設定の自動化
- ヒューマンIKの設定を自動化
- ヒューマンIKの設定を保存・ロード

"""

import json
import re

import maya.cmds as cmds
import maya.mel as mel

from ywta.rig import humanik_assignment


def _mel_string(value):
    """Python文字列をMELの文字列literalとして安全に表現する。"""
    return json.dumps(str(value), ensure_ascii=False)


# 選択したJointの階層からバインドポーズのリストを取得してすべてバインドポーズにする。
def goto_bind_pose(joint):
    # joint = cmds.ls(sl=True, type="joint")
    joint_hierarchy = cmds.listRelatives(joint, allDescendents=True, type="joint")
    bindPoses = cmds.dagPose(joint_hierarchy, q=True, bp=True)

    for bp in bindPoses:
        cmds.dagPose(bp, g=True, restore=True)


# 正規表現で選択したJointの子階層から検索する
def find_joint_with_regexp(joint, reg):
    """選択Jointの子孫から正規表現に一致するJointを1つ返す。

    この関数は既存スクリプト向けの互換APIとして、最初に一致した
    Jointだけを返します。HumanIKの事前検証では曖昧な一致を許可しない
    内部候補解決を使用します。
    """
    joint_hierarchy = cmds.listRelatives(joint, allDescendents=True, type="joint") or []
    for candidate in joint_hierarchy:
        if re.search(reg, candidate):
            return candidate
    return None


def _find_joint_candidates(joint, reg):
    """選択Jointの子孫から正規表現に一致するJointを決定的に列挙する。"""
    joint_hierarchy = cmds.listRelatives(joint, allDescendents=True, type="joint", fullPath=True) or []

    def matches(candidate):
        leaf_name = candidate.rsplit("|", 1)[-1].rsplit(":", 1)[-1]
        return re.search(reg, leaf_name) is not None

    return sorted(
        (candidate for candidate in joint_hierarchy if matches(candidate)),
        key=lambda candidate: (candidate.casefold(), candidate),
    )


def _preflight_hik_character():
    """HumanIK作成前の選択とHip/Pelvis解決を検証する。

    この関数はMaya sceneを変更しない読み取り専用処理で、検証済みの
    ``(root_joint, hip_joint)`` と元のJoint選択を返します。
    """
    previous_selection = cmds.ls(sl=True, long=True) or []
    if len(previous_selection) != 1:
        raise ValueError("HumanIK Auto Setupにはroot jointを1つだけ選択してください")

    root_joint = previous_selection[0]
    if cmds.nodeType(root_joint) != "joint":
        raise ValueError("HumanIK Auto Setupにはroot jointを1つだけ選択してください")

    hip_candidates = _find_joint_candidates(root_joint, r"(?i)(hip|pelvis)")
    if not hip_candidates:
        raise ValueError("root joint階層からHipまたはPelvisを解決できません")
    if len(hip_candidates) > 1:
        raise ValueError("root joint階層のHip/Pelvis候補が曖昧です: {}".format(", ".join(hip_candidates)))

    return root_joint, hip_candidates[0], list(previous_selection)


def create_character(name):
    # create character Definition
    new_character = mel.eval(f'hikCreateCharacter( "{name}" );')
    mel.eval("hikUpdateCharacterList();")
    mel.eval("hikSelectDefinitionTab();")
    mel.eval(f'hikSetCurrentCharacter("{new_character}");')

    return new_character


def load_character_definition(file_path):
    """検証済みJSONから現在のHumanIK Characterへslotを割り当てる。

    全slot IDと全target Jointを読み取り専用で解決してから適用を始める。
    targetが存在しない、Jointでない、または名前が曖昧な場合はsceneを
    変更しない。
    """
    character_config = humanik_assignment.load(file_path)

    hikChar = mel.eval("hikGetCurrentCharacter()")

    resolved_slots = []
    for assignment in character_config["assignments"]:
        bone_id = mel.eval(f"hikGetNodeIdFromName({_mel_string(assignment['slot'])})")
        if not isinstance(bone_id, int) or isinstance(bone_id, bool) or bone_id < 0:
            raise ValueError("HumanIK slotを解決できません: {}".format(assignment["slot"]))
        resolved_slots.append((assignment, bone_id))

    resolved = []
    for assignment, bone_id in resolved_slots:
        target = assignment["target"]
        target_nodes = cmds.ls(target, long=True) or []
        if not target_nodes:
            raise ValueError("HumanIK targetが存在しません: {}".format(target))
        if len(target_nodes) > 1:
            raise ValueError("HumanIK target Jointが曖昧です: {}".format(target))

        target_joints = cmds.ls(target_nodes[0], long=True, type="joint") or []
        if len(target_joints) != 1 or target_joints[0] != target_nodes[0]:
            raise ValueError("HumanIK targetはJointではありません: {}".format(target))
        resolved.append((target_joints[0], bone_id))

    for target_joint, bone_id in resolved:
        mel.eval(
            "setCharacterObject({},{},{},0)".format(
                _mel_string(target_joint),
                _mel_string(hikChar),
                bone_id,
            )
        )


def setup_hik_character():
    """選択したroot jointから限定的なHumanIK Characterを設定する。

    Character作成やMEL呼び出しの前に選択とHip/Pelvis候補を検証する。
    成功・失敗にかかわらず、途中で変更した選択は元へ戻す。
    """
    root_joint, hip_joint, previous_selection = _preflight_hik_character()

    try:
        new_character = create_character("testCharacter")
        cmds.select(hip_joint, replace=True)
        mel.eval(f"hikSetCharacterObject({_mel_string(hip_joint)},{_mel_string(new_character)},1,0)")
        mel.eval("hikUpdateDefinitionUI();")

        mel.eval(f'hikCharacterLock("{new_character}", 1,1);')
        # mel.eval("hikCreateControlRig;")
        mel.eval("hikUpdateDefinitionUI();")
    finally:
        cmds.select(previous_selection, replace=True)
