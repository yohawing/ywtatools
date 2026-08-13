"""HumanIK slot assignment を表す Maya 非依存の JSON 契約。"""

from __future__ import absolute_import

import json


FORMAT = "ywta.humanik-assignment"
VERSION = 1
_ROOT_FIELDS = {"format", "version", "assignments"}
_ASSIGNMENT_FIELDS = {"slot", "target"}
_LEGACY_ASSIGNMENT_FIELDS = {"target"}


def _non_empty_string(value, label):
    """前後の空白だけではない文字列を検証する。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} は空でない文字列にしてください。".format(label))
    return value


def validate(data):
    """versioned assignment 契約を検証し、決定的な順序のコピーを返す。"""
    if not isinstance(data, dict) or set(data) != _ROOT_FIELDS:
        raise ValueError("HumanIK assignment のroot fieldsが不正です。")
    if data.get("format") != FORMAT:
        raise ValueError("YWTA HumanIK assignment ファイルではありません。")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != VERSION:
        raise ValueError("未対応の HumanIK assignment version です: {}".format(version))

    assignments = data.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("assignments はlistにしてください。")

    normalized = []
    slots = set()
    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict) or set(assignment) != _ASSIGNMENT_FIELDS:
            raise ValueError("assignment {} のfieldsが不正です。".format(index))
        slot = _non_empty_string(assignment.get("slot"), "assignment {} のslot".format(index))
        target = _non_empty_string(assignment.get("target"), "assignment {} のtarget".format(index))
        if slot in slots:
            raise ValueError("slot が重複しています: {}".format(slot))
        slots.add(slot)
        normalized.append({"slot": slot, "target": target})

    normalized.sort(key=lambda item: item["slot"])
    return {"format": FORMAT, "version": VERSION, "assignments": normalized}


def _normalize_legacy(data):
    """旧形式の slot -> target record を versioned 契約へ変換する。"""
    assignments = []
    for slot, record in data.items():
        _non_empty_string(slot, "legacy slot")
        if not isinstance(record, dict) or set(record) != _LEGACY_ASSIGNMENT_FIELDS:
            raise ValueError("legacy assignment {} のfieldsが不正です。".format(slot))
        assignments.append({"slot": slot, "target": record.get("target")})
    return validate({"format": FORMAT, "version": VERSION, "assignments": assignments})


def normalize(data):
    """versioned契約または旧形式を検証済みのversioned契約へ揃える。"""
    if not isinstance(data, dict):
        raise ValueError("HumanIK assignment はdictにしてください。")
    if set(data) & _ROOT_FIELDS:
        return validate(data)
    return _normalize_legacy(data)


def load(file_path):
    """JSONファイルを読み込み、検証済みのversioned契約を返す。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        return normalize(json.load(handle))


def merge(*layers):
    """assignment layerを左から重ね、同一slotは後のlayerで上書きする。"""
    assignments = {}
    for layer in layers:
        normalized = normalize(layer)
        for assignment in normalized["assignments"]:
            assignments[assignment["slot"]] = assignment["target"]
    return validate(
        {
            "format": FORMAT,
            "version": VERSION,
            "assignments": [{"slot": slot, "target": target} for slot, target in assignments.items()],
        }
    )


def preview_merge(base, *overrides):
    """入力を変更せずにassignment layerの統合結果と差分を返す。"""
    normalized_layers = [normalize(layer) for layer in (base,) + overrides]
    merged = merge(*normalized_layers)
    before_by_slot = {assignment["slot"]: assignment["target"] for assignment in normalized_layers[0]["assignments"]}

    changes = []
    for assignment in merged["assignments"]:
        slot = assignment["slot"]
        before = before_by_slot.get(slot)
        after = assignment["target"]
        if before is None:
            status = "added"
        elif before == after:
            status = "unchanged"
        else:
            status = "changed"
        changes.append(
            {
                "slot": slot,
                "before": before,
                "after": after,
                "status": status,
            }
        )

    return {"merged": merged, "changes": changes}
