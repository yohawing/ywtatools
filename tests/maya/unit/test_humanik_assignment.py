"""HumanIK assignment JSON契約を検証する。"""

import unittest

from ywta.rig import humanik_assignment


class HumanIkAssignmentTests(unittest.TestCase):
    def _data(self, assignments):
        """version 1契約のテストデータを返す。"""
        return {
            "format": humanik_assignment.FORMAT,
            "version": humanik_assignment.VERSION,
            "assignments": assignments,
        }

    def test_validate_returns_assignments_in_slot_order(self):
        data = self._data(
            [
                {"slot": "Spine", "target": "rig:spine"},
                {"slot": "Hips", "target": "rig:hips"},
            ]
        )

        result = humanik_assignment.validate(data)

        self.assertEqual(["Hips", "Spine"], [item["slot"] for item in result["assignments"]])

    def test_normalize_accepts_legacy_mapping(self):
        result = humanik_assignment.normalize(
            {
                "Spine": {"target": "rig:spine"},
                "Hips": {"target": "rig:hips"},
            }
        )

        self.assertEqual(humanik_assignment.FORMAT, result["format"])
        self.assertEqual(["Hips", "Spine"], [item["slot"] for item in result["assignments"]])

    def test_merge_uses_later_assignment_for_same_slot(self):
        base = self._data(
            [
                {"slot": "Hips", "target": "detected:hips"},
                {"slot": "Spine", "target": "detected:spine"},
            ]
        )
        override = {"Hips": {"target": "manual:hips"}}

        result = humanik_assignment.merge(base, override)

        self.assertEqual(
            [
                {"slot": "Hips", "target": "manual:hips"},
                {"slot": "Spine", "target": "detected:spine"},
            ],
            result["assignments"],
        )

    def test_rejects_unknown_root_field(self):
        data = self._data([])
        data["confidence"] = "high"

        with self.assertRaises(ValueError):
            humanik_assignment.validate(data)

    def test_rejects_unknown_assignment_field(self):
        data = self._data([{"slot": "Hips", "target": "hips", "confidence": "high"}])

        with self.assertRaises(ValueError):
            humanik_assignment.validate(data)

    def test_rejects_unknown_version_and_bool_version(self):
        for version in (2, True):
            with self.subTest(version=version):
                data = self._data([])
                data["version"] = version
                with self.assertRaises(ValueError):
                    humanik_assignment.validate(data)

    def test_rejects_empty_slot_or_target(self):
        invalid = (
            [{"slot": " ", "target": "hips"}],
            [{"slot": "Hips", "target": ""}],
        )
        for assignments in invalid:
            with self.subTest(assignments=assignments):
                with self.assertRaises(ValueError):
                    humanik_assignment.validate(self._data(assignments))

    def test_rejects_duplicate_slot(self):
        data = self._data(
            [
                {"slot": "Hips", "target": "hipsA"},
                {"slot": "Hips", "target": "hipsB"},
            ]
        )

        with self.assertRaises(ValueError):
            humanik_assignment.validate(data)

    def test_legacy_record_rejects_unknown_field(self):
        with self.assertRaises(ValueError):
            humanik_assignment.normalize({"Hips": {"target": "hips", "confidence": "high"}})


if __name__ == "__main__":
    unittest.main()
