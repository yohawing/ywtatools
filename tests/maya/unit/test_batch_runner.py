"""Batch Runner の Maya subprocess 統合テスト。"""

import io
import json
import os
import sys
from unittest import mock

import maya.cmds as cmds

from ywta.pipeline import batch_runner
from ywta.test import TestCase


class BatchRunnerTests(TestCase):
    """scene ごとの mayapy 隔離と失敗継続を検証する。"""

    def _scene(self, name):
        path = self.get_temp_filename(name + ".ma")
        cmds.file(new=True, force=True)
        cmds.createNode("transform", name="asset")
        cmds.file(rename=path)
        cmds.file(save=True, type="mayaAscii", force=True)
        return path

    def test_batch_runs_each_scene_in_fresh_process_and_saves(self):
        first = self._scene("first")
        second = self._scene("second")
        script = """
if cmds.objExists('process_sentinel'):
    raise RuntimeError('scene was not isolated')
cmds.createNode('transform', name='process_sentinel')
cmds.addAttr('asset', longName='batchValue', attributeType='long')
cmds.setAttr('asset.batchValue', 42)
"""

        results = batch_runner.run_batch([first, second], script=script, save=True, mayapy_path=sys.executable)

        self.assertEqual(["ok", "ok"], [result["report"]["status"] for result in results])
        for scene in (first, second):
            cmds.file(scene, open=True, force=True)
            self.assertEqual(42, cmds.getAttr("asset.batchValue"))

    def test_batch_continues_after_scene_failure(self):
        bad = self._scene("bad")
        good = self._scene("good")
        script = """
import os
if os.path.basename(cmds.file(query=True, sceneName=True)).startswith('bad'):
    raise RuntimeError('expected failure')
cmds.addAttr('asset', longName='completed', attributeType='bool')
cmds.setAttr('asset.completed', True)
"""

        results = batch_runner.run_batch([bad, good], script=script, save=True, mayapy_path=sys.executable)

        self.assertEqual(["error", "ok"], [result["report"]["status"] for result in results])
        cmds.file(good, open=True, force=True)
        self.assertTrue(cmds.getAttr("asset.completed"))

    def test_validate_scenes_deduplicates_case_insensitively(self):
        scene = self._scene("single")

        result = batch_runner.validate_scenes([scene, os.path.abspath(scene)])

        self.assertEqual([os.path.abspath(scene)], result)

    def test_invalid_script_is_rejected_before_process_launch(self):
        scene = self._scene("invalid_script")

        with mock.patch.object(batch_runner.subprocess, "Popen") as popen:
            with self.assertRaises(ValueError) as context:
                batch_runner.run_batch(
                    [scene],
                    script="if True print('broken')",
                    mayapy_path=sys.executable,
                )

        self.assertIn("line 1", str(context.exception))
        popen.assert_not_called()

    def test_cancel_stops_before_launching_next_scene(self):
        first = self._scene("first")
        second = self._scene("second")
        cancelled = {"value": False}

        def on_log(line):
            if line.startswith("[batch] RESULT"):
                cancelled["value"] = True

        results = batch_runner.run_batch(
            [first, second],
            mayapy_path=sys.executable,
            on_log=on_log,
            cancel_requested=lambda: cancelled["value"],
        )

        self.assertEqual(1, len(results))
        self.assertEqual(
            os.path.normcase(os.path.abspath(first)),
            os.path.normcase(results[0]["scene"]),
        )

    def test_malformed_child_report_becomes_error_and_batch_continues(self):
        first = self._scene("first")
        second = self._scene("second")
        launches = {"count": 0}

        class FakeProcess:
            """reportだけを生成する即時終了process。"""

            def __init__(self, arguments, **_kwargs):
                self.stdout = io.StringIO("")
                self.returncode = 0
                report_path = arguments[3]
                launches["count"] += 1
                with open(report_path, "w", encoding="utf-8") as handle:
                    if launches["count"] == 1:
                        handle.write("{broken")
                    else:
                        json.dump(
                            {
                                "scene": arguments[2],
                                "status": "ok",
                                "stages": ["opened"],
                            },
                            handle,
                        )

            def poll(self):
                return self.returncode

        with mock.patch.object(batch_runner.subprocess, "Popen", FakeProcess):
            results = batch_runner.run_batch(
                [first, second],
                mayapy_path=sys.executable,
            )

        self.assertEqual(["error", "ok"], [item["report"]["status"] for item in results])
        self.assertIn("読み込めません", results[0]["report"]["error"])
