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
            leftovers = [name for name in os.listdir(os.path.dirname(scene)) if name.startswith(".ywta_batch_scene_")]
            self.assertFalse(leftovers)

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

    def test_save_rejects_script_that_renames_current_scene(self):
        """Save checkboxで入力scene以外を暗黙保存しない。"""
        scene = self._scene("source")
        redirected = self.get_temp_filename("redirected.ma")
        script = "cmds.file(rename={!r})".format(redirected)

        results = batch_runner.run_batch(
            [scene],
            script=script,
            save=True,
            mayapy_path=sys.executable,
        )

        self.assertEqual("error", results[0]["report"]["status"])
        self.assertIn("scene path", results[0]["report"]["error"])
        self.assertFalse(os.path.exists(redirected))

    def test_validate_scenes_deduplicates_case_insensitively(self):
        scene = self._scene("single")

        result = batch_runner.validate_scenes([scene, os.path.abspath(scene)])

        self.assertEqual([os.path.abspath(scene)], result)

    def test_saved_ui_state_rejects_wrong_json_types(self):
        """壊れたQSettings値をUI widgetへ渡さない。"""
        self.assertIsNone(batch_runner.validate_state("[]"))
        self.assertIsNone(
            batch_runner.validate_state(
                json.dumps(
                    {
                        "version": batch_runner.STATE_VERSION,
                        "scenes": "scene.ma",
                        "script": 42,
                        "save": 1,
                    }
                )
            )
        )

    def test_saved_ui_state_accepts_complete_versioned_payload(self):
        """正しい保存状態は型を変えず復元する。"""
        state = {
            "version": batch_runner.STATE_VERSION,
            "scenes": ["asset.ma"],
            "script": "print('ok')",
            "save": False,
        }

        self.assertEqual(state, batch_runner.validate_state(json.dumps(state)))

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

    def test_scene_timeout_terminates_child_and_continues(self):
        """停止childを終了し、次sceneのfresh processへ進む。"""
        first = self._scene("timeout")
        second = self._scene("next")
        script = """
import os
import time
if os.path.basename(cmds.file(query=True, sceneName=True)).startswith('timeout'):
    time.sleep(10)
"""

        results = batch_runner.run_batch(
            [first, second],
            script=script,
            mayapy_path=sys.executable,
            scene_timeout=6.0,
        )

        self.assertEqual(["error", "ok"], [result["report"]["status"] for result in results])
        self.assertIn("timeout", results[0]["report"]["error"])

    def test_invalid_scene_timeout_rejects_before_process_launch(self):
        scene = self._scene("invalid_timeout")

        with mock.patch.object(batch_runner.subprocess, "Popen") as popen:
            with self.assertRaises(ValueError):
                batch_runner.run_batch([scene], mayapy_path=sys.executable, scene_timeout=0)

        popen.assert_not_called()

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
                with open(arguments[2], "r", encoding="utf-8") as payload_handle:
                    scene = json.load(payload_handle)["scene"]
                launches["count"] += 1
                with open(report_path, "w", encoding="utf-8") as handle:
                    if launches["count"] == 1:
                        handle.write("{broken")
                    else:
                        json.dump(
                            {
                                "scene": scene,
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

    def test_process_launch_failure_becomes_result_and_batch_continues(self):
        """Popen失敗をscene errorへ変換して後続sceneを処理する。"""
        first = self._scene("first")
        second = self._scene("second")
        launches = {"count": 0}

        class FakeProcess:
            """2回目だけ正常reportを返す即時process。"""

            def __init__(self, arguments, **_kwargs):
                launches["count"] += 1
                if launches["count"] == 1:
                    raise PermissionError("expected launch failure")
                self.stdout = io.StringIO("")
                self.returncode = 0
                with open(arguments[2], "r", encoding="utf-8") as payload_handle:
                    payload = json.load(payload_handle)
                with open(arguments[3], "w", encoding="utf-8") as handle:
                    json.dump(
                        {"scene": payload["scene"], "status": "ok", "stages": ["opened"]},
                        handle,
                    )

            def poll(self):
                return self.returncode

        with mock.patch.object(batch_runner.subprocess, "Popen", FakeProcess):
            results = batch_runner.run_batch([first, second], mayapy_path=sys.executable)

        self.assertEqual(["error", "ok"], [item["report"]["status"] for item in results])
        self.assertIsNone(results[0]["returncode"])
        self.assertIn("起動できません", results[0]["report"]["error"])

    def test_nonzero_child_exit_overrides_success_report(self):
        scene = self._scene("nonzero")

        class FakeProcess:
            """success report後に非0終了したchildを模倣する。"""

            def __init__(self, arguments, **_kwargs):
                self.stdout = io.StringIO("")
                self.returncode = 7
                with open(arguments[2], "r", encoding="utf-8") as payload_handle:
                    payload = json.load(payload_handle)
                with open(arguments[3], "w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "scene": payload["scene"],
                            "status": "ok",
                            "stages": ["opened"],
                        },
                        handle,
                    )

            def poll(self):
                return self.returncode

        with mock.patch.object(batch_runner.subprocess, "Popen", FakeProcess):
            results = batch_runner.run_batch(
                [scene],
                mayapy_path=sys.executable,
            )

        self.assertEqual("error", results[0]["report"]["status"])
        self.assertIn("7", results[0]["report"]["error"])

    def test_report_for_different_scene_is_rejected(self):
        scene = self._scene("expected")
        report = self.get_temp_filename("wrong_report.json")
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "scene": self.get_temp_filename("other.ma"),
                    "status": "ok",
                    "stages": [],
                },
                handle,
            )

        result = batch_runner._read_report(report, scene)

        self.assertEqual("error", result["status"])
        self.assertIn("形式が不正", result["error"])
