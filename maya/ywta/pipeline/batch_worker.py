"""Batch Runner が scene ごとに起動する mayapy child process。"""

from __future__ import absolute_import

import json
import os
import sys
import tempfile
import traceback


def _write_report(path, report):
    """child report を原子的に書き出す。"""
    directory = os.path.dirname(os.path.abspath(path))
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".ywta_batch_report_",
        suffix=".tmp",
        delete=False,
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def run(payload_path, report_path):
    """1 scene を Maya standalone で処理し report を返す。"""
    with open(payload_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    scene = payload["scene"]
    script = payload.get("script", "")
    save = payload.get("save", False)
    report = {"scene": scene, "status": "error", "stages": []}
    initialized = False
    try:
        import maya.standalone

        maya.standalone.initialize(name="python")
        initialized = True
        import maya.cmds as cmds

        print("[batch] OPEN {}".format(scene), flush=True)
        cmds.file(scene, open=True, force=True, prompt=False)
        report["stages"].append("opened")
        if script.strip():
            print("[batch] SCRIPT {}".format(scene), flush=True)
            scope = {"__name__": "__main__", "__file__": "<ywta-batch-script>", "cmds": cmds}
            exec(compile(script, "<ywta-batch-script>", "exec"), scope, scope)
            report["stages"].append("script_ok")
        if save:
            current_scene = cmds.file(query=True, sceneName=True)
            if os.path.normcase(os.path.abspath(current_scene)) != os.path.normcase(os.path.abspath(scene)):
                raise RuntimeError("script実行後のscene pathが入力sceneと一致しません: {}".format(current_scene))
            print("[batch] SAVE {}".format(scene), flush=True)
            cmds.file(save=True, force=True)
            report["stages"].append("saved")
        report["status"] = "ok"
        print("[batch] OK {}".format(scene), flush=True)
    except Exception as error:
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
        print("[batch] ERROR {}: {}".format(scene, error), flush=True)
    finally:
        try:
            _write_report(report_path, report)
        finally:
            if initialized:
                try:
                    import maya.standalone

                    maya.standalone.uninitialize()
                except Exception:
                    pass
    return 0 if report["status"] == "ok" else 1


def main(argv=None):
    """CLI entry point。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: batch_worker.py PAYLOAD_JSON REPORT_JSON", file=sys.stderr)
        return 2
    return run(argv[0], argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
