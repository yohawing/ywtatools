"""scene ごとに独立 mayapy を起動する cancellable Maya Batch Runner。"""

from __future__ import absolute_import

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

import maya.cmds as cmds

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    from PySide2.QtCore import QSettings
    from PySide2.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )


STATE_VERSION = 1
SCENE_EXTENSIONS = {".ma", ".mb"}


def validate_scenes(scenes):
    """scene list を重複なしの絶対パスへ検証・正規化する。"""
    if not isinstance(scenes, (list, tuple)) or not scenes:
        raise ValueError("Maya scene を1つ以上指定してください。")
    result = []
    seen = set()
    for scene in scenes:
        if not isinstance(scene, str) or not scene.strip():
            raise ValueError("scene path が不正です。")
        path = os.path.abspath(scene)
        key = os.path.normcase(path)
        if Path(path).suffix.lower() not in SCENE_EXTENSIONS:
            raise ValueError("Maya scene ではありません: {}".format(path))
        if not os.path.isfile(path):
            raise ValueError("scene file がありません: {}".format(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def resolve_mayapy():
    """現在の Maya または環境から mayapy executable を解決する。"""
    executable = Path(sys.executable)
    if executable.name.lower() in {"mayapy", "mayapy.exe"} and executable.is_file():
        return str(executable)
    candidates = []
    maya_location = os.environ.get("MAYA_LOCATION")
    if maya_location:
        candidates.append(Path(maya_location) / "bin" / "mayapy.exe")
    try:
        install_directory = cmds.about(installDirectory=True)
    except Exception:
        install_directory = None
    if install_directory:
        candidates.append(Path(install_directory) / "bin" / "mayapy.exe")
    for version in range(2030, 2021, -1):
        candidates.append(Path("C:/Program Files/Autodesk/Maya{}".format(version)) / "bin" / "mayapy.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("mayapy.exe を解決できません。MAYA_LOCATION を設定してください。")


def _stream_reader(stream, output_queue):
    """child stdout を background thread で行単位に読む。"""
    try:
        for line in iter(stream.readline, ""):
            output_queue.put(line.rstrip("\r\n"))
    finally:
        stream.close()


def _drain_output(output_queue, logs, on_log):
    """queue 済み stdout を log callback へ転送する。"""
    while True:
        try:
            line = output_queue.get_nowait()
        except queue.Empty:
            return
        logs.append(line)
        if on_log:
            on_log(line)


def _write_payload(path, payload):
    """child payload JSON を書き出す。"""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run_batch(
    scenes,
    script="",
    save=False,
    mayapy_path=None,
    on_log=None,
    cancel_requested=None,
    on_wait=None,
):
    """scene ごとに新しい mayapy を起動して順次処理する。

    Cancel は実行中 process を強制終了せず、現在 scene 完了後に新規起動を止める。
    """
    scenes = validate_scenes(scenes)
    if not isinstance(script, str):
        raise ValueError("script は文字列にしてください。")
    if not isinstance(save, bool):
        raise ValueError("save は bool にしてください。")
    mayapy_path = os.path.abspath(mayapy_path or resolve_mayapy())
    if not os.path.isfile(mayapy_path):
        raise ValueError("mayapy がありません: {}".format(mayapy_path))
    worker = os.path.join(os.path.dirname(__file__), "batch_worker.py")
    maya_root = str(Path(__file__).resolve().parents[2])
    results = []
    with tempfile.TemporaryDirectory(prefix="ywta_batch_") as temporary:
        for index, scene in enumerate(scenes):
            if cancel_requested and cancel_requested():
                if on_log:
                    on_log("[batch] CANCELLED before {}".format(scene))
                break
            payload_path = os.path.join(temporary, "payload_{}.json".format(index))
            report_path = os.path.join(temporary, "report_{}.json".format(index))
            _write_payload(
                payload_path,
                {"scene": scene, "script": script, "save": save},
            )
            if on_log:
                on_log("[batch] START {}".format(scene))
            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = os.pathsep.join(value for value in [maya_root, existing_pythonpath] if value)
            environment["PYTHONUTF8"] = "1"
            process = subprocess.Popen(
                [mayapy_path, worker, payload_path, report_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
            )
            output_queue = queue.Queue()
            logs = []
            reader = threading.Thread(
                target=_stream_reader,
                args=(process.stdout, output_queue),
                daemon=True,
            )
            reader.start()
            while process.poll() is None:
                _drain_output(output_queue, logs, on_log)
                if on_wait:
                    on_wait()
                time.sleep(0.05)
            reader.join(timeout=2.0)
            _drain_output(output_queue, logs, on_log)
            report = None
            if os.path.isfile(report_path):
                with open(report_path, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
            if report is None:
                report = {
                    "scene": scene,
                    "status": "error",
                    "error": "child report がありません。",
                    "stages": [],
                }
            result = {
                "scene": scene,
                "returncode": process.returncode,
                "report": report,
                "logs": logs,
            }
            results.append(result)
            if on_log:
                on_log("[batch] RESULT {} {}".format(report.get("status", "error").upper(), scene))
    return results


class BatchRunnerWindow(QMainWindow):
    """scene list、script、save、cancel を提供する Batch Runner UI。"""

    def __init__(self, parent=None):
        super(BatchRunnerWindow, self).__init__(parent)
        self.setWindowTitle("YWTA Batch Runner")
        self.resize(760, 680)
        self._cancelled = False
        self._settings = QSettings("ywtatools", "BatchRunner")
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("Scenes"))
        self.scene_list = QListWidget()
        layout.addWidget(self.scene_list)
        scene_buttons = QHBoxLayout()
        add_button = QPushButton("Add Scenes")
        remove_button = QPushButton("Remove Selected")
        clear_button = QPushButton("Clear")
        add_button.clicked.connect(self._add_scenes)
        remove_button.clicked.connect(self._remove_selected)
        clear_button.clicked.connect(self.scene_list.clear)
        for button in (add_button, remove_button, clear_button):
            scene_buttons.addWidget(button)
        layout.addLayout(scene_buttons)
        layout.addWidget(QLabel("Python Script (optional, headless Maya)"))
        self.script_edit = QPlainTextEdit()
        layout.addWidget(self.script_edit)
        self.save_checkbox = QCheckBox("Save each scene in place")
        layout.addWidget(self.save_checkbox)
        run_buttons = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.cancel_button = QPushButton("Cancel after current scene")
        self.cancel_button.setEnabled(False)
        self.run_button.clicked.connect(self._run)
        self.cancel_button.clicked.connect(self._request_cancel)
        run_buttons.addWidget(self.run_button)
        run_buttons.addWidget(self.cancel_button)
        layout.addLayout(run_buttons)
        layout.addWidget(QLabel("Log"))
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit)
        self._restore_state()

    def _add_scenes(self):
        paths, _selected_filter = QFileDialog.getOpenFileNames(self, "Add Maya Scenes", "", "Maya Scenes (*.ma *.mb)")
        existing = {os.path.normcase(self.scene_list.item(index).text()) for index in range(self.scene_list.count())}
        for path in paths:
            if os.path.normcase(path) not in existing:
                existing.add(os.path.normcase(path))
                self.scene_list.addItem(path)

    def _remove_selected(self):
        for item in self.scene_list.selectedItems():
            self.scene_list.takeItem(self.scene_list.row(item))

    def _request_cancel(self):
        self._cancelled = True
        self._append_log("[batch] cancel requested; current scene will finish")

    def _append_log(self, line):
        self.log_edit.appendPlainText(line)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _run(self):
        scenes = [self.scene_list.item(index).text() for index in range(self.scene_list.count())]
        self._cancelled = False
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._save_state()
        try:
            run_batch(
                scenes,
                script=self.script_edit.toPlainText(),
                save=self.save_checkbox.isChecked(),
                on_log=self._append_log,
                cancel_requested=lambda: self._cancelled,
                on_wait=QApplication.processEvents,
            )
        except Exception as error:
            self._append_log("[batch] ERROR {}".format(error))
        finally:
            self.run_button.setEnabled(True)
            self.cancel_button.setEnabled(False)

    def _save_state(self):
        state = {
            "version": STATE_VERSION,
            "scenes": [self.scene_list.item(index).text() for index in range(self.scene_list.count())],
            "script": self.script_edit.toPlainText(),
            "save": self.save_checkbox.isChecked(),
        }
        self._settings.setValue("state", json.dumps(state, ensure_ascii=False))

    def _restore_state(self):
        raw = self._settings.value("state", "")
        try:
            state = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            state = {}
        if state.get("version") != STATE_VERSION:
            return
        for scene in state.get("scenes", []):
            if isinstance(scene, str):
                self.scene_list.addItem(scene)
        self.script_edit.setPlainText(state.get("script", ""))
        self.save_checkbox.setChecked(bool(state.get("save", False)))

    def closeEvent(self, event):
        """window close 時に versioned state を保存する。"""
        self._save_state()
        super(BatchRunnerWindow, self).closeEvent(event)


_WINDOW = None


def show():
    """Batch Runner window を表示する。"""
    global _WINDOW
    if _WINDOW:
        _WINDOW.close()
    _WINDOW = BatchRunnerWindow()
    _WINDOW.show()
    return _WINDOW
