"""ヒューマンIK関連のモジュールと便利スクリプト

Functions:
- モーションデータのインポートと設定の自動化
- ヒューマンIKの設定を自動化
- ヒューマンIKの設定を保存・ロード

"""

import os
import json
import re
import maya.cmds as cmds
import maya.mel as mel
import pymel.core as pm

import mgear


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


# XMLファイルからHumanIKのキャラクター定義の設定をロードする
def load_character_definition(file_path):
    character_config = {}

    with open(file_path, "r") as fp:
        character_config = json.load(fp)

    hikChar = pm.mel.hikGetCurrentCharacter()

    # ctls = [pm.PyNode(character_config[bone]["target"]) for bone in character_config]

    for bone in character_config:
        bone_id = pm.mel.hikGetNodeIdFromName(bone)
        pm.mel.setCharacterObject(character_config[bone]["target"], hikChar, bone_id, 0)


def setup_hik_character():
    # Select Root Joint and setup HumanIK
    joint = cmds.ls(sl=True, type="joint")[0]
    new_character = create_character("testCharacter")

    # set hip bone for character
    hip_joint = find_joint_with_regexp(joint, r"(?i)(hip|pelvis)")
    cmds.select(hip_joint)

    pm.mel.hikSetCharacterObject(hip_joint, new_character, 1, 0)
    mel.eval("hikUpdateDefinitionUI();")

    # ここで止まる
    load_character_definition(
        r"F:\3dcg\Nix\nixx_maya\data\moveai_character_definition.hikm"
    )

    mel.eval(f'hikCharacterLock("{new_character}", 1,1);')
    # mel.eval("hikCreateControlRig;")
    mel.eval("hikUpdateDefinitionUI();")
