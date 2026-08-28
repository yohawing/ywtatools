import sys
import importlib
import ywta

DEFAULT_RELOAD_PACKAGES = ["ywta"]


def _close_playback_ui_before_reload():
    """既存Playback Sessionをreload前に解放し、失敗時はreloadを止める。"""

    playback_ui = sys.modules.get("ywta.link.playback_ui")
    if playback_ui is None:
        return
    close = getattr(playback_ui, "close", None)
    if callable(close):
        close()


class RollbackImporter(object):
    """Used to remove imported modules from the module list.

    This allows tests to be rerun after code updates without doing any reloads.
    Original idea from: http://pyunit.sourceforge.net/notes/reloading.html

    Usage:
    def run_tests(self):
        if self.rollback_importer:
            self.rollback_importer.uninstall()
        self.rollback_importer = RollbackImporter()
        self.load_and_execute_tests()
    """

    def __init__(self):
        """Creates an instance and installs as the global importer"""
        self.previous_modules = set(sys.modules.keys())

    def uninstall(self):
        """
        importlib.reloadを使って、モジュールをアンインストールします。
        この関数は、前回のモジュールのリストに存在しない現在のシステムモジュールに対して
        リロードを試みます。これにより、次回インポート時に強制的にリロードされます。
        注意：
            - 例外が発生した場合は無視されます。
            - 実際には削除ではなく、importlib.reloadを使用してモジュールをリロードします。
        戻り値:
            None
        """

        _close_playback_ui_before_reload()
        for modname in sys.modules.keys():
            if modname not in self.previous_modules:
                # Force reload when modname next imported
                try:
                    # del(sys.modules[modname])
                    importlib.reload(sys.modules[modname])
                    print(f"Unloaded: {modname}")
                except Exception:
                    pass

    def unload_packages(self, packages=None):
        """
        指定されたパッケージをアンロードし、再ロードします。
        パッケージが指定されていない場合は、DEFAULT_RELOAD_PACKAGESをデフォルトとして使用します。
        sys.modules内の各モジュールをチェックし、指定されたパッケージで始まるものをリロードします。
        最後に、ywta.initialize()を呼び出してモジュールを初期化します。
        Args:
            packages (list, optional): リロードするパッケージ名のリスト。Noneの場合、DEFAULT_RELOAD_PACKAGESが使用されます。
        Returns:
            None
        """

        if packages is None:
            packages = DEFAULT_RELOAD_PACKAGES

        _close_playback_ui_before_reload()

        # construct reload list
        reloadList = []
        for i in sys.modules.keys():
            for package in packages:
                if i.startswith(package):
                    reloadList.append(i)

        # unload everything
        for modname in reloadList:
            try:
                if sys.modules[modname] is not None:
                    importlib.reload(sys.modules[modname])
                    print(f"Unloaded: {modname}")
            except Exception:
                print(f"Failed to unload: {modname}")

        ywta.initialize()


_rollbackimporter = RollbackImporter()


def save_modules():
    global _rollbackimporter
    _rollbackimporter = RollbackImporter()


def reload_modules():
    global _rollbackimporter
    _rollbackimporter.uninstall()


def unload_packages(modnames=None):
    global _rollbackimporter
    _rollbackimporter.unload_packages(modnames)
