"""HumanIK helperがPyMELなしでMELを組み立てることを検証する。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ywta.rig import humanik


class HumanIkTests(unittest.TestCase):
    @staticmethod
    def _assignment(*items):
        return {
            "format": "ywta.humanik-assignment",
            "version": 1,
            "assignments": [{"slot": slot, "target": target} for slot, target in items],
        }

    def _assert_setup_rejected_without_mutation(self, selected_joints, descendants):
        with (
            mock.patch.object(humanik.cmds, "ls", return_value=selected_joints),
            mock.patch.object(humanik.cmds, "nodeType", return_value="joint"),
            mock.patch.object(humanik.cmds, "listRelatives", return_value=descendants),
            mock.patch.object(humanik, "create_character") as create_character,
            mock.patch.object(humanik.mel, "eval") as evaluate,
        ):
            with self.assertRaises(ValueError):
                humanik.setup_hik_character()

        create_character.assert_not_called()
        evaluate.assert_not_called()

    def test_setup_rejects_unselected_root_before_mutation(self):
        self._assert_setup_rejected_without_mutation([], [])

    def test_setup_rejects_multiple_selected_roots_before_mutation(self):
        self._assert_setup_rejected_without_mutation(["root_a", "root_b"], [])

    def test_setup_rejects_root_and_mesh_selection_before_mutation(self):
        self._assert_setup_rejected_without_mutation(["root", "mesh"], [])

    def test_setup_rejects_missing_hip_before_mutation(self):
        self._assert_setup_rejected_without_mutation(["root"], ["spine", "chest"])

    def test_setup_ignores_hip_in_ancestor_path(self):
        self._assert_setup_rejected_without_mutation(["root"], ["|hip_group|spine"])

    def test_setup_rejects_ambiguous_hip_before_mutation(self):
        self._assert_setup_rejected_without_mutation(["root"], ["pelvis", "hip_joint"])

    def test_setup_resolves_unique_hip_and_restores_selection(self):
        with (
            mock.patch.object(humanik.cmds, "ls", return_value=["|rig|root"]),
            mock.patch.object(humanik.cmds, "nodeType", return_value="joint"),
            mock.patch.object(
                humanik.cmds,
                "listRelatives",
                return_value=["spine", "pelvis_joint"],
            ) as list_relatives,
            mock.patch.object(humanik.cmds, "select") as select,
            mock.patch.object(humanik, "create_character", return_value="Character1") as create_character,
            mock.patch.object(humanik.mel, "eval") as evaluate,
        ):
            humanik.setup_hik_character()

        create_character.assert_called_once_with("testCharacter")
        self.assertEqual(
            [
                'hikSetCharacterObject("pelvis_joint","Character1",1,0)',
                "hikUpdateDefinitionUI();",
                'hikCharacterLock("Character1", 1,1);',
                "hikUpdateDefinitionUI();",
            ],
            [call.args[0] for call in evaluate.call_args_list],
        )
        self.assertEqual(
            [
                mock.call("pelvis_joint", replace=True),
                mock.call(["|rig|root"], replace=True),
            ],
            select.call_args_list,
        )
        list_relatives.assert_called_once_with("|rig|root", allDescendents=True, type="joint", fullPath=True)

    def test_setup_restores_selection_when_mel_fails(self):
        with (
            mock.patch.object(humanik.cmds, "ls", return_value=["|rig|root"]),
            mock.patch.object(humanik.cmds, "nodeType", return_value="joint"),
            mock.patch.object(humanik.cmds, "listRelatives", return_value=["pelvis_joint"]),
            mock.patch.object(humanik.cmds, "select") as select,
            mock.patch.object(humanik, "create_character", return_value="Character1"),
            mock.patch.object(humanik.mel, "eval", side_effect=RuntimeError("MEL failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "MEL failed"):
                humanik.setup_hik_character()

        self.assertEqual(
            [
                mock.call("pelvis_joint", replace=True),
                mock.call(["|rig|root"], replace=True),
            ],
            select.call_args_list,
        )

    def test_load_character_definition_uses_maya_mel_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "character.json"
            path.write_text(json.dumps({"LeftArm": {"target": 'joint"Left'}}), encoding="utf-8")

            with (
                mock.patch.object(
                    humanik.mel,
                    "eval",
                    side_effect=["Character1", 9, None],
                ) as evaluate,
                mock.patch.object(
                    humanik.cmds,
                    "ls",
                    side_effect=[['|rig|joint"Left'], ['|rig|joint"Left']],
                ) as list_nodes,
            ):
                humanik.load_character_definition(path)

        self.assertEqual(evaluate.call_args_list[0].args[0], "hikGetCurrentCharacter()")
        self.assertEqual(evaluate.call_args_list[1].args[0], 'hikGetNodeIdFromName("LeftArm")')
        self.assertEqual(
            evaluate.call_args_list[2].args[0],
            'setCharacterObject("|rig|joint\\"Left","Character1",9,0)',
        )
        self.assertEqual(
            [
                mock.call('joint"Left', long=True),
                mock.call('|rig|joint"Left', long=True, type="joint"),
            ],
            list_nodes.call_args_list,
        )

    def test_load_character_definition_validates_before_mel_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "ywta.humanik-assignment",
                        "version": 1,
                        "assignments": [{"slot": "LeftArm", "target": ""}],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(humanik.mel, "eval") as evaluate:
                with self.assertRaises(ValueError):
                    humanik.load_character_definition(path)

        evaluate.assert_not_called()

    def test_load_character_definition_resolves_all_slots_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-slot.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "ywta.humanik-assignment",
                        "version": 1,
                        "assignments": [
                            {"slot": "Spine", "target": "rig:spine"},
                            {"slot": "Hips", "target": "rig:hips"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                humanik.mel,
                "eval",
                side_effect=["Character1", 1, -1],
            ) as evaluate:
                with self.assertRaisesRegex(ValueError, "Spine"):
                    humanik.load_character_definition(path)

        self.assertEqual(
            [
                "hikGetCurrentCharacter()",
                'hikGetNodeIdFromName("Hips")',
                'hikGetNodeIdFromName("Spine")',
            ],
            [call.args[0] for call in evaluate.call_args_list],
        )
        self.assertFalse(any(call.args[0].startswith("setCharacterObject") for call in evaluate.call_args_list))

    def test_load_character_definition_resolves_all_targets_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-target.json"
            path.write_text(
                json.dumps(
                    {
                        "format": "ywta.humanik-assignment",
                        "version": 1,
                        "assignments": [
                            {"slot": "Hips", "target": "rig:hips"},
                            {"slot": "Spine", "target": "rig:spine"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    humanik.mel,
                    "eval",
                    side_effect=["Character1", 1, 8],
                ) as evaluate,
                mock.patch.object(
                    humanik.cmds,
                    "ls",
                    side_effect=[["|rig|hips"], ["|rig|hips"], []],
                ) as list_nodes,
            ):
                with self.assertRaisesRegex(ValueError, "rig:spine"):
                    humanik.load_character_definition(path)

        self.assertEqual(
            [
                mock.call("rig:hips", long=True),
                mock.call("|rig|hips", long=True, type="joint"),
                mock.call("rig:spine", long=True),
            ],
            list_nodes.call_args_list,
        )
        self.assertFalse(any(call.args[0].startswith("setCharacterObject") for call in evaluate.call_args_list))

    def test_load_character_definition_rejects_non_joint_target_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "non-joint-target.json"
            path.write_text(json.dumps({"Hips": {"target": "hips_mesh"}}), encoding="utf-8")

            with (
                mock.patch.object(
                    humanik.mel,
                    "eval",
                    side_effect=["Character1", 1],
                ) as evaluate,
                mock.patch.object(
                    humanik.cmds,
                    "ls",
                    side_effect=[["|rig|hips_mesh"], []],
                ),
            ):
                with self.assertRaisesRegex(ValueError, "Jointではありません"):
                    humanik.load_character_definition(path)

        self.assertFalse(any(call.args[0].startswith("setCharacterObject") for call in evaluate.call_args_list))

    def test_load_character_definition_rejects_ambiguous_target_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous-target.json"
            path.write_text(json.dumps({"Hips": {"target": "hips"}}), encoding="utf-8")

            with (
                mock.patch.object(
                    humanik.mel,
                    "eval",
                    side_effect=["Character1", 1],
                ) as evaluate,
                mock.patch.object(
                    humanik.cmds,
                    "ls",
                    return_value=["|first|hips", "|second|hips"],
                ),
            ):
                with self.assertRaisesRegex(ValueError, "曖昧"):
                    humanik.load_character_definition(path)

        self.assertFalse(any(call.args[0].startswith("setCharacterObject") for call in evaluate.call_args_list))

    def test_load_character_definition_applies_long_targets_in_slot_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ordered-targets.json"
            path.write_text(
                json.dumps(
                    {
                        "Spine": {"target": "spine"},
                        "Hips": {"target": "hips"},
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    humanik.mel,
                    "eval",
                    side_effect=["Character1", 1, 8, None, None],
                ) as evaluate,
                mock.patch.object(
                    humanik.cmds,
                    "ls",
                    side_effect=[
                        ["|rig|hips"],
                        ["|rig|hips"],
                        ["|rig|spine"],
                        ["|rig|spine"],
                    ],
                ),
            ):
                humanik.load_character_definition(path)

        self.assertEqual(
            [
                'setCharacterObject("|rig|hips","Character1",1,0)',
                'setCharacterObject("|rig|spine","Character1",8,0)',
            ],
            [call.args[0] for call in evaluate.call_args_list[3:]],
        )

    def test_create_definition_sets_and_reads_back_in_slot_order(self):
        assignment = self._assignment(("Spine", "spine"), ("Hips", "hips"))
        mel_results = {
            'hikGetNodeIdFromName("Hips")': 1,
            'hikGetNodeIdFromName("Spine")': 8,
            "hikGetSceneCharacters()": [],
            'hikCreateCharacter("Hero");': "Hero1",
            'hikGetSkNode("Hero1",1)': "hips",
            'hikGetSkNode("Hero1",8)': "spine",
        }

        with (
            mock.patch.object(
                humanik.cmds,
                "ls",
                side_effect=[
                    ["|rig|hips"],
                    ["|rig|hips"],
                    ["|rig|spine"],
                    ["|rig|spine"],
                    ["|rig|hips"],
                    ["|rig|spine"],
                ],
            ),
            mock.patch.object(
                humanik.mel,
                "eval",
                side_effect=lambda command: mel_results.get(command),
            ) as evaluate,
        ):
            result = humanik.create_character_definition(assignment, "Hero")

        self.assertEqual(result, "Hero1")
        commands = [call.args[0] for call in evaluate.call_args_list]
        self.assertEqual(
            [
                'setCharacterObject("|rig|hips","Hero1",1,0)',
                'setCharacterObject("|rig|spine","Hero1",8,0)',
            ],
            [command for command in commands if command.startswith("setCharacterObject")],
        )
        self.assertEqual(
            ['hikGetSkNode("Hero1",1)', 'hikGetSkNode("Hero1",8)'],
            [command for command in commands if command.startswith("hikGetSkNode")],
        )
        self.assertFalse(
            any(
                token in command
                for command in commands
                for token in ("hikCharacterLock", "hikSetCurrentCharacter", "hikUpdateDefinitionUI")
            )
        )

    def test_create_definition_rejects_empty_before_creation(self):
        with mock.patch.object(humanik.mel, "eval") as evaluate:
            with self.assertRaisesRegex(ValueError, "1件以上"):
                humanik.create_character_definition(self._assignment())

        evaluate.assert_not_called()

    def test_create_definition_rejects_unknown_slot_before_creation(self):
        with mock.patch.object(humanik.mel, "eval", return_value=-1) as evaluate:
            with self.assertRaisesRegex(ValueError, "Unknown"):
                humanik.create_character_definition(self._assignment(("Unknown", "joint")))

        self.assertFalse(any("hikCreateCharacter" in call.args[0] for call in evaluate.call_args_list))

    def test_create_definition_rejects_invalid_targets_before_creation(self):
        cases = (
            ([], "存在しません"),
            (["|a|joint", "|b|joint"], "曖昧"),
            (["|rig|mesh"], "Jointではありません"),
        )
        for target_result, message in cases:
            with self.subTest(message=message):
                list_results = [target_result]
                if target_result == ["|rig|mesh"]:
                    list_results.append([])
                with (
                    mock.patch.object(humanik.cmds, "ls", side_effect=list_results),
                    mock.patch.object(humanik.mel, "eval", return_value=1) as evaluate,
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        humanik.create_character_definition(self._assignment(("Hips", "target")))

                self.assertFalse(any("hikCreateCharacter" in call.args[0] for call in evaluate.call_args_list))

    def test_create_definition_cleans_up_when_second_set_fails(self):
        assignment = self._assignment(("Hips", "hips"), ("Spine", "spine"))

        def evaluate(command):
            if command == 'hikGetNodeIdFromName("Hips")':
                return 1
            if command == 'hikGetNodeIdFromName("Spine")':
                return 8
            if command == 'hikCreateCharacter("YWTACharacter");':
                return "Character1"
            if command == 'setCharacterObject("|rig|spine","Character1",8,0)':
                raise RuntimeError("set failed")
            if command == "hikGetSceneCharacters()":
                return []
            return None

        with (
            mock.patch.object(
                humanik.cmds,
                "ls",
                side_effect=[
                    ["|rig|hips"],
                    ["|rig|hips"],
                    ["|rig|spine"],
                    ["|rig|spine"],
                ],
            ),
            mock.patch.object(humanik.mel, "eval", side_effect=evaluate) as mel_eval,
        ):
            with self.assertRaises(humanik.HumanIkCharacterCreationError) as raised:
                humanik.create_character_definition(assignment)

        error = raised.exception
        self.assertEqual(error.character, "Character1")
        self.assertEqual(str(error.creation_error), "set failed")
        self.assertIsNone(error.cleanup_error)
        self.assertIs(error.__cause__, error.creation_error)
        self.assertIn(
            mock.call('hikDeleteCharacter("Character1");'),
            mel_eval.call_args_list,
        )

    def test_create_definition_cleans_up_empty_or_wrong_readback(self):
        for readback in ("", "other_joint"):
            with self.subTest(readback=readback):

                def evaluate(command):
                    if command == 'hikGetNodeIdFromName("Hips")':
                        return 1
                    if command == 'hikCreateCharacter("YWTACharacter");':
                        return "Character1"
                    if command == 'hikGetSkNode("Character1",1)':
                        return readback
                    if command == "hikGetSceneCharacters()":
                        return []
                    return None

                readback_result = [] if not readback else ["|rig|other_joint"]
                with (
                    mock.patch.object(
                        humanik.cmds,
                        "ls",
                        side_effect=[
                            ["|rig|hips"],
                            ["|rig|hips"],
                            readback_result,
                        ],
                    ),
                    mock.patch.object(humanik.mel, "eval", side_effect=evaluate) as mel_eval,
                ):
                    with self.assertRaises(humanik.HumanIkCharacterCreationError) as raised:
                        humanik.create_character_definition(self._assignment(("Hips", "hips")))

                self.assertIn("readback", str(raised.exception.creation_error))
                self.assertIn(
                    mock.call('hikDeleteCharacter("Character1");'),
                    mel_eval.call_args_list,
                )

    def test_create_definition_preserves_cleanup_failure_details(self):
        def evaluate(command):
            if command == 'hikGetNodeIdFromName("Hips")':
                return 1
            if command == 'hikCreateCharacter("YWTACharacter");':
                return "Character1"
            if command.startswith("setCharacterObject"):
                raise RuntimeError("set failed")
            if command.startswith("hikDeleteCharacter"):
                raise RuntimeError("delete failed")
            if command == "hikGetSceneCharacters()":
                return []
            return None

        with (
            mock.patch.object(
                humanik.cmds,
                "ls",
                side_effect=[["|rig|hips"], ["|rig|hips"]],
            ),
            mock.patch.object(humanik.mel, "eval", side_effect=evaluate),
        ):
            with self.assertRaises(humanik.HumanIkCharacterCreationError) as raised:
                humanik.create_character_definition(self._assignment(("Hips", "hips")))

        self.assertEqual(str(raised.exception.creation_error), "set failed")
        self.assertEqual(str(raised.exception.cleanup_error), "delete failed")

    def test_create_definition_cleans_up_character_when_create_returns_empty(self):
        def evaluate(command):
            if command == 'hikGetNodeIdFromName("Hips")':
                return 1
            if command == "hikGetSceneCharacters()":
                evaluate.scene_reads += 1
                if evaluate.scene_reads == 1:
                    return []
                return ["Character1"] if evaluate.scene_reads == 2 else []
            if command == 'hikCreateCharacter("YWTACharacter");':
                return ""
            return None

        evaluate.scene_reads = 0
        with (
            mock.patch.object(
                humanik.cmds,
                "ls",
                side_effect=[["|rig|hips"], ["|rig|hips"]],
            ),
            mock.patch.object(humanik.mel, "eval", side_effect=evaluate) as mel_eval,
        ):
            with self.assertRaises(humanik.HumanIkCharacterCreationError) as raised:
                humanik.create_character_definition(self._assignment(("Hips", "hips")))

        self.assertEqual(raised.exception.character, "Character1")
        self.assertIsNone(raised.exception.cleanup_error)
        self.assertIn(mock.call('hikDeleteCharacter("Character1");'), mel_eval.call_args_list)

    def test_cleanup_requires_verified_scene_character_absence(self):
        with mock.patch.object(
            humanik.mel,
            "eval",
            side_effect=[None, None],
        ):
            with self.assertRaisesRegex(RuntimeError, "確認できません"):
                humanik._cleanup_created_character("Character1")

    def test_cleanup_parses_delimited_scene_character_names(self):
        with mock.patch.object(
            humanik.mel,
            "eval",
            side_effect=[None, '"Character2";"Character3"'],
        ):
            humanik._cleanup_created_character("Character1")


if __name__ == "__main__":
    unittest.main()
