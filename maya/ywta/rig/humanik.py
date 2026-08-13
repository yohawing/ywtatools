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
    hip_joint = None
    joint_hierarchy = cmds.listRelatives(joint, allDescendents=True, type="joint")
    for joint in joint_hierarchy:
        if re.search(reg, joint):
            hip_joint = joint
            break
    return hip_joint


def create_character(name):
    # create character Definition
    new_character = mel.eval(f'hikCreateCharacter( "{name}" );')
    mel.eval("hikUpdateCharacterList();")
    mel.eval("hikSelectDefinitionTab();")
    mel.eval(f'hikSetCurrentCharacter("{new_character}");')

    return new_character


def load_character_definition(file_path):
    """検証済みJSONから現在のHumanIK Characterへslotを割り当てる。"""
    character_config = humanik_assignment.load(file_path)

    hikChar = mel.eval("hikGetCurrentCharacter()")

    resolved = []
    for assignment in character_config["assignments"]:
        bone_id = mel.eval(f"hikGetNodeIdFromName({_mel_string(assignment['slot'])})")
        if not isinstance(bone_id, int) or isinstance(bone_id, bool) or bone_id < 0:
            raise ValueError("HumanIK slotを解決できません: {}".format(assignment["slot"]))
        resolved.append((assignment, bone_id))

    for assignment, bone_id in resolved:
        mel.eval(
            "setCharacterObject({},{},{},0)".format(
                _mel_string(assignment["target"]),
                _mel_string(hikChar),
                bone_id,
            )
        )


def setup_hik_character():
    # Select Root Joint and setup HumanIK
    joint = cmds.ls(sl=True, type="joint")[0]
    new_character = create_character("testCharacter")

    # set hip bone for character
    hip_joint = find_joint_with_regexp(joint, r"(?i)(hip|pelvis)")
    cmds.select(hip_joint)

    mel.eval(f"hikSetCharacterObject({_mel_string(hip_joint)},{_mel_string(new_character)},1,0)")
    mel.eval("hikUpdateDefinitionUI();")

    mel.eval(f'hikCharacterLock("{new_character}", 1,1);')
    # mel.eval("hikCreateControlRig;")
    mel.eval("hikUpdateDefinitionUI();")
