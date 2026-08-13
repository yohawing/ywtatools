"""HumanIK helperがPyMELなしでMELを組み立てることを検証する。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ywta.rig import humanik


class HumanIkTests(unittest.TestCase):
    def test_load_character_definition_uses_maya_mel_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "character.json"
            path.write_text(json.dumps({"LeftArm": {"target": 'joint"Left'}}), encoding="utf-8")

            with mock.patch.object(
                humanik.mel,
                "eval",
                side_effect=["Character1", 9, None],
            ) as evaluate:
                humanik.load_character_definition(path)

        self.assertEqual(evaluate.call_args_list[0].args[0], "hikGetCurrentCharacter()")
        self.assertEqual(evaluate.call_args_list[1].args[0], 'hikGetNodeIdFromName("LeftArm")')
        self.assertEqual(
            evaluate.call_args_list[2].args[0],
            'setCharacterObject("joint\\"Left","Character1",9,0)',
        )


if __name__ == "__main__":
    unittest.main()
