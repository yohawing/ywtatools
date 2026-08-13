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


class HumanIkCharacterCreationError(RuntimeError):
    """HumanIK Character作成後の失敗とcleanup結果を保持する例外。"""

    def __init__(self, character, creation_error, cleanup_error=None):
        """作成処理とcleanup処理の例外を保持する。"""
        self.character = character
        self.creation_error = creation_error
        self.cleanup_error = cleanup_error
        message = "HumanIK Characterの作成に失敗しました: {}".format(character)
        if cleanup_error is not None:
            message += " (cleanupにも失敗: {})".format(cleanup_error)
        super().__init__(message)


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


def _resolve_assignments(assignment_data, require_non_empty=False):
    """assignmentを正規化し、slot IDとtarget Jointを事前解決する。"""
    normalized = humanik_assignment.normalize(assignment_data)
    if require_non_empty and not normalized["assignments"]:
        raise ValueError("HumanIK assignmentには1件以上のslotが必要です")

    resolved_slots = []
    for assignment in normalized["assignments"]:
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
        resolved.append((assignment["slot"], target_joints[0], bone_id))
    return resolved


def rebind_assignment_targets(root_joint, assignment_data):
    """論理Joint名のassignmentを指定root階層のlong DAG pathへ再束縛する。

    namespaceを除いたJointのleaf名だけをcase-sensitiveで完全一致させる。
    root階層外のscene nodeは検索せず、全targetが一意に解決できるまで
    HumanIKのMEL処理を呼び出さない読み取り専用APIである。

    Args:
        root_joint: 検索範囲にするroot Joint名。
        assignment_data: versionedまたはlegacyのassignment契約。

    Returns:
        targetをlong DAG pathへ置換したversion 1 assignment。

    Raises:
        ValueError: rootまたはtargetを一意に解決できない場合。
    """
    normalized = humanik_assignment.normalize(assignment_data)

    root_matches = cmds.ls(root_joint, long=True, type="joint") or []
    if len(root_matches) != 1:
        raise ValueError("HumanIK rebindのroot Jointを一意に解決できません: {}".format(root_joint))
    root_path = root_matches[0]

    descendants = (
        cmds.listRelatives(
            root_path,
            allDescendents=True,
            type="joint",
            fullPath=True,
        )
        or []
    )
    hierarchy = [root_path]
    hierarchy.extend(candidate for candidate in descendants if candidate.startswith(root_path + "|"))

    candidates_by_logical_name = {}
    for candidate in dict.fromkeys(hierarchy):
        logical_name = candidate.rsplit("|", 1)[-1].rsplit(":", 1)[-1]
        candidates_by_logical_name.setdefault(logical_name, []).append(candidate)

    rebound = []
    used_targets = set()
    for assignment in normalized["assignments"]:
        target = assignment["target"]
        candidates = candidates_by_logical_name.get(target, [])
        if not candidates:
            raise ValueError("HumanIK targetをroot Joint階層から解決できません: {}".format(target))
        if len(candidates) > 1:
            raise ValueError("HumanIK targetがroot Joint階層内で曖昧です: {}".format(target))
        resolved_target = candidates[0]
        if resolved_target in used_targets:
            raise ValueError("複数のHumanIK slotが同じJointへ解決されました: {}".format(resolved_target))
        used_targets.add(resolved_target)
        rebound.append({"slot": assignment["slot"], "target": resolved_target})

    return humanik_assignment.validate(
        {
            "format": humanik_assignment.FORMAT,
            "version": humanik_assignment.VERSION,
            "assignments": rebound,
        }
    )


def _cleanup_created_character(character):
    """所有するCharacterを削除し、sceneから消えたことを確認する。"""
    mel.eval("hikDeleteCharacter({});".format(_mel_string(character)))
    scene_characters = _scene_humanik_characters()
    if character in scene_characters:
        raise RuntimeError("HumanIK Characterをsceneから削除できませんでした: {}".format(character))


def _scene_humanik_characters():
    """MELのscene Character返値を検証済みの名前集合へ変換する。"""
    raw_characters = mel.eval("hikGetSceneCharacters()")
    if raw_characters is None:
        raise RuntimeError("scene内のHumanIK Characterを確認できませんでした")
    if isinstance(raw_characters, str):
        stripped = raw_characters.strip()
        if not stripped:
            return set()
        characters = re.split(r"[;\s]+", stripped)
    elif isinstance(raw_characters, (list, tuple)):
        characters = raw_characters
    else:
        raise RuntimeError("HumanIK Character一覧の返値が不正です")
    if any(not isinstance(character, str) or not character.strip().strip('"') for character in characters):
        raise RuntimeError("HumanIK Character一覧に不正な名前があります")
    return {character.strip().strip('"') for character in characters}


def create_character_definition(assignment_data, name_hint="YWTACharacter"):
    """検証済みassignmentから新規HumanIK Characterを構築する。

    全slotとJointをscene変更前に解決します。作成後の割り当てまたは
    readback検証に失敗した場合は、この関数が作成したCharacterだけを
    削除し、元の失敗とcleanup結果を例外へ保持します。
    """
    if not isinstance(name_hint, str) or not name_hint.strip():
        raise ValueError("HumanIK Character名は空でない文字列にしてください")
    resolved = _resolve_assignments(assignment_data, require_non_empty=True)

    characters_before = _scene_humanik_characters()
    character = None
    try:
        character = mel.eval("hikCreateCharacter({});".format(_mel_string(name_hint)))
        if not isinstance(character, str) or not character.strip():
            raise RuntimeError("HumanIK Characterを作成できませんでした")
    except Exception as creation_error:
        cleanup_error = None
        try:
            created_characters = _scene_humanik_characters() - characters_before
            if len(created_characters) > 1:
                raise RuntimeError("作成されたHumanIK Characterを一意に特定できません")
            if created_characters:
                character = next(iter(created_characters))
                _cleanup_created_character(character)
        except Exception as error:
            cleanup_error = error
        raise HumanIkCharacterCreationError(character, creation_error, cleanup_error) from creation_error

    try:
        for _slot, target_joint, bone_id in resolved:
            mel.eval(
                "setCharacterObject({},{},{},0)".format(
                    _mel_string(target_joint),
                    _mel_string(character),
                    bone_id,
                )
            )

        for slot, expected_joint, bone_id in resolved:
            readback = mel.eval(
                "hikGetSkNode({},{})".format(
                    _mel_string(character),
                    bone_id,
                )
            )
            if not isinstance(readback, str) or not readback.strip():
                raise RuntimeError("HumanIK slotのreadbackが空です: {}".format(slot))
            readback_joints = cmds.ls(readback, long=True, type="joint") or []
            if len(readback_joints) != 1 or readback_joints[0] != expected_joint:
                raise RuntimeError(
                    "HumanIK slotのreadbackが一致しません: {} (expected={}, actual={})".format(
                        slot,
                        expected_joint,
                        readback,
                    )
                )
        return character
    except Exception as creation_error:
        cleanup_error = None
        try:
            _cleanup_created_character(character)
        except Exception as error:
            cleanup_error = error
        raise HumanIkCharacterCreationError(character, creation_error, cleanup_error) from creation_error


def load_character_definition(file_path):
    """検証済みJSONから現在のHumanIK Characterへslotを割り当てる。

    全slot IDと全target Jointを読み取り専用で解決してから適用を始める。
    targetが存在しない、Jointでない、または名前が曖昧な場合はsceneを
    変更しない。
    """
    character_config = humanik_assignment.load(file_path)

    hikChar = mel.eval("hikGetCurrentCharacter()")

    resolved = _resolve_assignments(character_config)

    for _slot, target_joint, bone_id in resolved:
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
